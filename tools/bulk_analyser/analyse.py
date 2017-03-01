#!/usr/bin/env python3
"""analyse.py: batch analyses smart contracts and categorises them."""

## IMPORTS

import os
from os.path import abspath, dirname, join
import argparse
import re
from multiprocessing import Process, SimpleQueue, Manager, Event
import subprocess
import time
import sys
import itertools
import json

# Add the source directory to the path to ensure the imports work
src_path = join(dirname(abspath(__file__)), "../../src")
sys.path.insert(0, src_path)

# Local project imports
import dataflow
import tac_cfg
import opcodes
import exporter
import logger
ll = logger.log_low


## Constants

DEFAULT_SOUFFLE_BIN = '../../../souffle/src/souffle'
"""Location of the Souffle binary."""

DEFAULT_CONTRACT_DIR = 'contracts'
"""Directory to fetch contract files from by default."""

DEFAULT_RESULTS_FILE = 'results.json'
"""File to write results to by default."""

DEFAULT_SPEC_DL = 'spec.dl'
"""Vulnerability specification file."""

TEMP_WORKING_DIR = ".temp"
"""Scratch working directory."""

DEFAULT_TIMEOUT = 120
"""Default time before killing analysis of a contract."""

DEFAULT_MAX_ITER = -1
"""Default max analysis iteration count."""

DEFAULT_BAILOUT = -1
"""Default analysis bailout time in seconds."""

DEFAULT_PATTERN = ".*runtime.hex"
"""Default filename pattern for contract files."""

FLUSH_PERIOD = 3
"""Wait a little to flush the files and join the processes when concluding."""

DOMINATORS = False
"""Whether or not the cfg relations should include dominators"""

OPCODES = []
"""A list of strings indicating which opcodes to include in the cfg relations."""

DEFAULT_NUM_JOBS = 4
"""The number of subprocesses to run at once."""


## Command Line Arguments

parser = argparse.ArgumentParser(
  description="A batch analyser for EVM bytecode programs.")

parser.add_argument("-c",
                    "--contract_dir",
                    nargs="?",
                    default=DEFAULT_CONTRACT_DIR,
                    const=DEFAULT_CONTRACT_DIR,
                    metavar="DIR",
                    help="the location to grab contracts from (as bytecode "
                         "files).")

parser.add_argument("-S",
                    "--souffle_bin",
                    nargs="?",
                    default=DEFAULT_SOUFFLE_BIN,
                    const=DEFAULT_SOUFFLE_BIN,
                    metavar="BINARY",
                    help="the location of the souffle binary.")

parser.add_argument("-C",
                    "--compile_souffle",
                    action="store_true",
                    default=False,
                    help="compile souffle step.")

parser.add_argument("-p",
                    "--filename_pattern",
                    nargs="?",
                    default=DEFAULT_PATTERN,
                    const=DEFAULT_PATTERN,
                    metavar="REGEX",
                    help="A regular expression. Only filenames matching it "
                         "will be processed.")

parser.add_argument("-r",
                    "--results_file",
                    nargs="?",
                    default=DEFAULT_RESULTS_FILE,
                    const=DEFAULT_RESULTS_FILE,
                    metavar="FILE",
                    help="the location to write the results.")

parser.add_argument("-f",
                    "--from_file",
                    nargs="?",
                    default=None,
                    metavar="FILE",
                    help="A file to extract the filenames of the contracts "
                         "to analyse from, rather than simply processing all "
                         "files in the contracts directory.")

parser.add_argument("-j",
                    "--jobs",
                    type=int,
                    nargs="?",
                    default=DEFAULT_NUM_JOBS,
                    const=DEFAULT_NUM_JOBS,
                    metavar="NUM",
                    help="The number of subprocesses to run at once.")

parser.add_argument("-n",
                    "--num_contracts",
                    type=int,
                    nargs="?",
                    default=None,
                    metavar="NUM",
                    help="The maximum number of contracts to process in this "
                         "batch. Unlimited by default.")

parser.add_argument("-k",
                    "--skip",
                    type=int,
                    nargs="?",
                    default=0,
                    const=0,
                    metavar="NUM",
                    help="Skip the the analysis of the first NUM contracts.")

parser.add_argument("-T",
                    "--timeout_secs",
                    type=int,
                    nargs="?",
                    default=DEFAULT_TIMEOUT,
                    const=DEFAULT_TIMEOUT,
                    metavar="SECONDS",
                    help="Forcibly halt analysing any single contact after "
                         "the specified number of seconds.")

parser.add_argument("-i",
                    "--max_iter",
                    type=int,
                    nargs="?",
                    default=DEFAULT_MAX_ITER,
                    const=DEFAULT_MAX_ITER,
                    metavar="ITERATIONS",
                    help="perform no more than the specified number of "
                         "analysis iterations. Lower is faster, but "
                         "potentially less precise. A negative value specifies "
                         "no cap on the iteration count. No cap by default.")

parser.add_argument("-t",
                    "--bail_time",
                    type=int,
                    nargs="?",
                    default=DEFAULT_BAILOUT,
                    const=DEFAULT_BAILOUT,
                    metavar="SECONDS",
                    help="begin to terminate the analysis if it's looking to "
                         "take more time than the specified number of seconds. "
                         "Bailing out early may mean the analysis is not able "
                         "to reach a fixed-point, so results may be less "
                         "precise. A negative value means no cap on the "
                         "running time. No cap by default.")

parser.add_argument("-q",
                    "--quiet",
                    action="store_true",
                    default=False,
                    help="Silence output.")

parser.add_argument("-s",
                    "--strict",
                    action="store_true",
                    default=False,
                    help="unrecognised opcodes will not be skipped, but will "
                         "result in an error.")


## Functions

def aquire_tsv_settings() -> None:
  """
  Determine, by examining the input datalog spec,
  whether dominators or any particular opcode relations
  need to be produced by the decompiler as tsv files.
  """
 
  global DOMINATORS
  global OPCODES
  dom_prefixes = ["dom", "pdom", "imdom", "impdom"]

  with open(DEFAULT_SPEC_DL, 'r') as dl:
    for line in dl:
      splitline = line.strip().split()
      if len(splitline) < 2:
        continue
      if splitline[0] == ".decl" and "input" in splitline:
        op_name = splitline[1][:splitline[1].index("(")]
        if op_name in dom_prefixes:
          DOMINATORS = True
        if op_name.startswith("op_") and op_name[3:] in opcodes.OPCODES:
          OPCODES.append(op_name[3:])


def working_dir(index:int, output_dir:bool=False) -> str:
  """
  Return a path to the working directory for the job
  indicated by index.

  Args:
   index: return the directory specifically for this index.
   output_dir: if true, return the output subdir, which souffle writes to.
  """

  if output_dir:
     return join(TEMP_WORKING_DIR, str(index), "out")
  return join(TEMP_WORKING_DIR, str(index))


def empty_working_dir(index) -> None:
  """
  Empty the working directory for the job indicated by index.
  """

  for d_triple in os.walk(working_dir(index)):
    for fname in d_triple[2]:
      os.remove(join(d_triple[0], fname))


def analyse_contract(job_index:int, index:int, filename:str, result_queue) -> None:
  """
  Perform dataflow analysis on a contract, storing the result in the queue.
  This is a worker function to be passed to a subprocess.

  Args:
      job_index: the job number for this invocation of analyse_contract
      index: the number of the particular contract being analysed
      filename: the location of the contract bytecode file to process
      result_queue: a multiprocessing queue in which to store the analysis results
  """

  try:
    with open(join(args.contract_dir, filename)) as file:
      # Decompile and perform dataflow analysis upon the given graph
      decomp_start = time.time()
      cfg = tac_cfg.TACGraph.from_bytecode(file, strict=args.strict)
      dataflow.analyse_graph(cfg, max_iterations=args.max_iter,
                                  bailout_seconds=args.bail_time)

      # Export relations to temp working directory
      empty_working_dir(job_index)
      work_dir = working_dir(job_index)
      out_dir = working_dir(job_index, True)
      exporter.CFGTsvExporter(cfg).export(output_dir=work_dir,
                                          dominators=DOMINATORS,
                                          out_opcodes=OPCODES)

      # Run souffle on those relations
      souffle_start = time.time()
      souffle_args = [args.souffle_bin, "--fact-dir={}".format(work_dir), 
                                        "--output-dir={}".format(out_dir),
                                        DEFAULT_SPEC_DL]
      if args.compile_souffle:
          souffle_args.append("--compile")
      subprocess.run(souffle_args)
      
      # Collect the results and put them in the result queue
      vulns = []
      for fname in os.listdir(out_dir):
        fpath = join(out_dir, fname)
        if os.path.getsize(fpath) != 0:
          vulns.append(fname.split(".")[0])

      flags = []
      if cfg.has_unresolved_jump:
        flags.append("UNRESOLVED")

      result_queue.put((filename, vulns, flags))
      
      # Decompile + Analysis time
      decomp_time = souffle_start - decomp_start
      souffle_time = time.time() - souffle_start
      ll("{}: {:.20}... completed in {:.2f} + {:.2f} secs".format(index, filename,
                                                                  decomp_time,
                                                                  souffle_time))
  except Exception as e:
    ll("Error: {}".format(e))
    result_queue.put((filename, [], ["ERROR"]))


def flush_queue(period, run_sig,
                result_queue, result_list):
  """
  For flushing the queue periodically to a list so it doesn't fill up.

  Args:
      period: flush the result_queue to result_list every period seconds
      run_sig: terminate when the Event run_sig is cleared.
      result_queue: the queue in which results accumulate before being flushed
      result_list: the final list of results.
  """
  while run_sig.is_set():
    time.sleep(period)
    while not result_queue.empty():
      item = result_queue.get()
      result_list.append(item)


## Main Body

args = parser.parse_args()

if args.quiet:
  logger.LOG_LEVEL = logger.Verbosity.SILENT
else:
  logger.LOG_LEVEL = logger.Verbosity.MEDIUM

ll("Setting up working directory {}.".format(TEMP_WORKING_DIR))
for i in range(args.jobs):
  os.makedirs(working_dir(i, True), exist_ok=True)
  empty_working_dir(i)

ll("Reading TSV settings.")
aquire_tsv_settings()

# Extract contract filenames.
ll("Processing contract names.")
if args.from_file:
  # Get contract filenames from a file if specified.
  with open(args.from_file, 'r') as f:
    unfiltered = [l.strip() for l in f.readlines()]
else:
  # Otherwise just get all contracts in the contract directory.
  unfiltered = os.listdir(args.contract_dir)

# Filter according to the given pattern.
re_string = args.filename_pattern
if not re_string.endswith("$"):
  re_string = re_string + "$"
pattern = re.compile(re_string)
runtime_files = filter(lambda filename: pattern.match(filename) is not None,
                       unfiltered)

stop_index = None if args.num_contracts is None else args.skip + args.num_contracts
to_process = itertools.islice(runtime_files, args.skip, stop_index)

ll("Setting up workers.")
# Set up multiprocessing result list and queue.
manager = Manager()

# This list contains analysis results as (filename, category, flags) triples.
res_list = manager.list()

# Holds results transiently before flushing to res_list
res_queue = SimpleQueue()

# Start the periodic flush process, only run while run_signal is set.
run_signal = Event()
run_signal.set()
flush_proc = Process(target=flush_queue, args=(FLUSH_PERIOD, run_signal,
                                               res_queue, res_list))
flush_proc.start()

workers = []
avail_jobs = list(range(args.jobs))
contract_iter = enumerate(to_process)
contracts_exhausted = False

ll("Analysing...\n")
try:
  while not contracts_exhausted:
   
    # If there's both workers and contracts available, use the former to work on the latter.
    while not contracts_exhausted and len(avail_jobs) > 0:
       try:
         index, fname = next(contract_iter)
         job_index = avail_jobs.pop()
         proc = Process(target=analyse_contract, args=(job_index, index, fname, res_queue))
         proc.start()
         start_time = time.time()
         workers.append({"name": fname, 
                         "proc": proc,
                         "time": start_time,
                         "job_index": job_index})
       except StopIteration:
         contracts_exhausted = True
    
    # Loop until some process terminates (to retask it) or, 
    # if there are no unanalysed contracts left, until currently-running contracts are done
    while len(avail_jobs) == 0 or (contracts_exhausted and 0 < len(workers)):
      to_remove = []
      for i in range(len(workers)):
        start_time = workers[i]["time"]
        proc = workers[i]["proc"]
        name = workers[i]["name"]
        job_index = workers[i]["job_index"]

        if time.time() - start_time > args.timeout_secs:
          res_queue.put((name, [], ["TIMEOUT"]))
          proc.terminate()
          ll("{} timed out.".format(name))
          to_remove.append(i)
          avail_jobs.append(job_index)
        elif not proc.is_alive():
          to_remove.append(i)
          proc.join()
          avail_jobs.append(job_index)
      
      # Reverse index order so as to pop elements correctly
      for i in reversed(to_remove):
        workers.pop(i)

      time.sleep(0.01)
  
  # Conclude and write results to file.
  ll("\nFinishing...\n")
  run_signal.clear()
  flush_proc.join(FLUSH_PERIOD + 1)

  counts = {}
  total_flagged = 0
  for contract, vulns, flags in res_list:
    rlist = vulns + flags
    if len(rlist) > 0:
      total_flagged += 1
    for res in rlist:
      if res not in counts:
        counts[res] = 1
      else:
        counts[res] += 1

  total = len(res_list)
  ll("{} of {} contracts flagged.\n".format(total_flagged, total))
  for res, count in counts.items():
    ll("  {}: {:.2f}%".format(res, 100*count/total))

  ll("\nWriting results to {}".format(args.results_file))
  with open(args.results_file, 'w') as f:
    f.write(json.dumps(list(res_list)))

except Exception as e:
  import traceback
  traceback.print_exc()
  flush_proc.terminate()

ll("Removing working directory {}".format(TEMP_WORKING_DIR))
import shutil
shutil.rmtree(TEMP_WORKING_DIR)


