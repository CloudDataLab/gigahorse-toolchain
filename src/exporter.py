"""exporter.py: abstract classes for exporting decompiler state"""

import abc
import csv
import os

import cfg
import opcodes
import patterns
import tac_cfg


class Exporter(abc.ABC):
  def __init__(self, source:object):
    """
    Args:
      source: object instance to be exported
    """
    self.source = source

  @abc.abstractmethod
  def export(self):
    """
    Exports the source object to an implementation-specific format.
    """


class CFGTsvExporter(Exporter, patterns.DynamicVisitor):
  """
  Generates .facts files of the given TAC CFG to local directory.

  Args:
    cfg: source TAC CFG to be exported to separate fact files.
  """
  def __init__(self, cfg:tac_cfg.TACGraph):
    super().__init__(cfg)
    self.ops = []
    """
    A list of pairs (op.pc, op.opcode), associating to each pc address the
    operation performed at that address.
    """

    self.edges = []
    """
    A list of edges between instructions defining a control flow graph.
    """

    self.defined = []
    """
    A list of pairs (op.pc, variable) that specify variable definition sites.
    """

    self.reads = []
    """
    A list of pairs (op.pc, variable) that specify all usage sites.
    """

    self.writes = []
    """
    A list of pairs (op.pc, variable) that specify all write locations.
    """

    self.block_nums = []
    """
    A list of pairs (op.pc, block.entry) that specify block numbers for each TACOp.
    """

    self.__prev_op = None
    """
    Previously visited TACOp.
    """

    self.__start_block = None
    """
    First BasicBlock visited, or None.
    """

    self.__end_block = None
    """
    Last BasicBlock visited, or None.
    """

    # Recursively visit the graph using a sorted traversal
    cfg.accept(self, generator=cfg.sorted_traversal())

  def visit_TACGraph(self, cfg):
    """
    Visit the TAC CFG root
    """
    pass

  def visit_TACBasicBlock(self, block):
    """
    Visit a TAC BasicBlock in the CFG
    """
    # Track the start and end blocks
    if self.__start_block is None:
      self.__start_block = block
    self.__end_block = block

    # Add edges from predecessor exits to this blocks's entry
    for pred in block.preds:
      # Generating edge.facts
      self.edges.append((hex(pred.last_op.pc), hex(block.tac_ops[0].pc)))

  def visit_TACOp(self, op):
    """
    Visit a TACOp in a BasicBlock of the CFG.
    """
    # Add edges between TACOps (generate edge.facts)
    if self.__prev_op != None:
      # Generating edge relations (edge.facts)
      self.edges.append((hex(self.__prev_op.pc), hex(op.pc)))
    self.__prev_op = op

    # Generate opcode relations (op.facts)
    self.ops.append((hex(op.pc), op.opcode))

    # Generate opcode to basic block relations (block.facts)
    self.block_nums.append((hex(op.pc), hex(op.block.entry)))

    if isinstance(op, tac_cfg.TACAssignOp):
      # Memory assignments are not considered as 'variable definitions'
      if not op.opcode in [opcodes.SLOAD, opcodes.MLOAD]:
        # Generate variable definition relations (defined.facts)
        self.defined.append((hex(op.pc), op.lhs))

      # TODO: Add notion of blockchain and local memory
      # Generate variable write relations (write.facts)
      self.writes.append((hex(op.pc), op.lhs))

    for arg in op.args:
      # Only include variable reads; ignore constants
      if isinstance(arg, tac_cfg.TACArg) and not arg.value.is_const:
        # Generate variable read relations (read.facts)
        self.reads.append((hex(op.pc), arg))

  def export(self, output_dir:str="", dominators:bool=False):
    """
    Export the CFG to separate fact files.

    ``op.facts``
      (program counter, operation) pairs
    ``defined.facts``
      variable definition locations
    ``read.facts``
      var/loc use locations
    ``write.facts``
      var/loc write locations
    ``edge.facts``
      instruction-level CFG edges
    ``start.facts``
      the first location of the CFG
    ``end.facts``
      the last location of the CFG

    If dominators is true:

    ``dom.facts``
    dominance relations
    ``imdom.facts``
    immediate dominance relations
    ``pdom.facts``
    post-dominance relations
    ``impdom.facts``
    immediate post-dominance relations

    Args:
      output_dir: the output directory where fact files should be written.
                  Will be created recursively if it doesn't exist.
      dominators: if true, also output files encoding dominance relations
    """
    # Create the target directory.
    if output_dir != "":
      os.makedirs(output_dir, exist_ok=True)

    def generate(filename, entries):
      path = os.path.join(output_dir, filename)

      with open(path, 'w') as f:
        writer = csv.writer(f, delimiter='\t', lineterminator='\n')
        for e in entries:
          writer.writerow(e)

    generate("op.facts", self.ops)
    generate("defined.facts", self.defined)
    generate("read.facts", self.reads)
    generate("write.facts", self.writes)
    generate("edge.facts", self.edges)
    generate("block.facts", self.block_nums)

    # Retrieve sorted list of blocks based on program counter
    # Note: Start and End are currently singletons
    # TODO -- Update starts and ends to be based on function boundaries
    start_fact = [hex(b.entry) for b in (self.__start_block,) if b is not None]
    end_fact = [hex(b.exit) for b in (self.__end_block,) if b is not None]
    generate("start.facts", [start_fact])
    generate("end.facts", [end_fact])

    if dominators:
      pairs = sorted([(k, i) for k, v in self.source.dominators().items()
                      for i in v])
      generate("dom.facts", pairs)
      pairs = sorted(self.source.immediate_dominators().items())
      generate("imdom.facts", pairs)

      pairs = sorted([(k, i) for k, v in self.source.dominators(True).items()
                      for i in v])
      generate("pdom.facts", pairs)
      pairs = sorted(self.source.immediate_dominators(True).items())
      generate("impdom.facts", pairs)


class CFGStringExporter(Exporter, patterns.DynamicVisitor):
  """
  Prints a textual representation of the given CFG to stdout.

  Args:
    cfg: source CFG to be printed.
    ordered: if True (default), print BasicBlocks in order of entry.
  """

  __BLOCK_SEP = "\n\n================================\n\n"

  def __init__(self, cfg:cfg.ControlFlowGraph, ordered:bool=True):
    super().__init__(cfg)
    self.ordered = ordered
    self.blocks = []
    self.source.accept(self)

  def visit_ControlFlowGraph(self, cfg):
    """
    Visit the CFG root
    """
    pass

  def visit_BasicBlock(self, block):
    """
    Visit a BasicBlock in the CFG
    """
    self.blocks.append((block.entry, str(block)))

  def export(self):
    """
    Print a textual representation of the input CFG to stdout.
    """
    if self.ordered:
      self.blocks.sort(key=lambda n: n[0])
    return self.__BLOCK_SEP.join(n[1] for n in self.blocks)


class CFGDotExporter(Exporter):
  """
  Generates a dot file for drawing a pretty picture of the given CFG.

  Args:
    cfg: source CFG to be exported to dot format.
  """
  def __init__(self, cfg:cfg.ControlFlowGraph):
    super().__init__(cfg)

  def export(self, out_filename:str="cfg.dot"):
    """
    Export the CFG to a dot file.

    Certain blocks will have coloured outlines:
      Green: contains a RETURN operation;
      Blue: contains a STOP operation;
      Red: contains a THROW or THROWI operation;
      Purple: contains a SUICIDE operation;

    A node with a red fill indicates that its stack size is large.

    Args:
      out_filename: path to the file where dot output should be written.
                    If the file extension is a supported image format,
                    attempt to generate an image using the `dot` program,
                    if it is in the user's `$PATH`.
    """
    import networkx as nx
    import os

    cfg = self.source

    G = cfg.nx_graph()

    # Colour-code the graph.
    returns = {block.ident(): "green" for block in cfg.blocks
               if block.last_op.opcode == opcodes.RETURN}
    stops = {block.ident(): "blue" for block in cfg.blocks
             if block.last_op.opcode == opcodes.STOP}
    throws = {block.ident(): "red" for block in cfg.blocks
             if block.last_op.opcode in [opcodes.THROW, opcodes.THROWI]}
    suicides = {block.ident(): "purple" for block in cfg.blocks
                if block.last_op.opcode == opcodes.SUICIDE}
    color_dict = {**returns, **stops, **throws, **suicides}
    nx.set_node_attributes(G, "color", color_dict)
    filldict = {b.ident(): "white" if len(b.entry_stack) <= 20 else "red"
                for b in cfg.blocks}
    nx.set_node_attributes(G, "fillcolor", filldict)
    nx.set_node_attributes(G, "style", "filled")

    # Annotate each node with its basic block's internal data for later display
    # if rendered in html.
    nx.set_node_attributes(G, "id", {block.ident(): block.ident()
                                     for block in cfg.blocks})
    block_strings = {}
    for block in cfg.blocks:
      block_string = str(block)
      def_site_string = "\n\nDef sites:\n"
      for v in block.entry_stack.value:
        def_site_string += str(v) \
                           + ": {" \
                           + ", ".join(str(d) for d in v.def_sites) \
                           + "}\n"
      block_strings[block.ident()] = block_string + def_site_string
    nx.set_node_attributes(G, "tooltip", block_strings)

    # Write non-dot files using pydot and Graphviz
    if "." in out_filename and not out_filename.endswith(".dot"):
      pdG = nx.nx_pydot.to_pydot(G)
      extension = out_filename.split(".")[-1]

      # If we're producing an html file, write a temporary svg to build it from
      # and then delete it.
      if extension == "html":
        import pagify as p
        tmpname = "." + out_filename + ".svg"
        pdG.write(tmpname, format="svg")
        p.pagify(tmpname, out_filename)
        os.remove(tmpname)
      else:
        pdG.write(out_filename, format=extension)

    # Otherwise, write a regular dot file using pydot
    else:
      if out_filename == "":
        out_filename = "cfg.dot"
      nx.nx_pydot.write_dot(G, out_filename)
