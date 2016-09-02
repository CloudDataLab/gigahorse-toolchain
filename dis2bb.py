#!/usr/bin/env python3

# Standard lib imports
import fileinput

# Local project imports
from cfglib import ControlFlowGraph
from stacksizeanalysis import run_analysis, block_stack_delta

cfg = ControlFlowGraph(fileinput.input())
entry, exit = run_analysis(cfg)

for block in cfg.blocks:
  print("Entry stack:", entry[block])
  print(block)
  print(block_stack_delta(block), "stack elements added.")
  print("Exit stack:", exit[block])
  print()
