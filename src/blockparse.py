"""blockparse.py: Parse operation sequences and construct basic blocks"""

import abc
import typing

import cfg
import evm_cfg
import opcodes
import logger

class BlockParser(abc.ABC):
  @abc.abstractmethod
  def __init__(self, raw:object):
    """
    Constructs a new BlockParser for parsing the given raw input object.

    Args:
      raw: parser-specific object containing raw input to be parsed.
    """

    self._raw = raw
    """raw: parser-specific object containing raw input to be parsed."""

    self._ops = []
    """
    List of program operations extracted from the raw input object.
    Indices from this list are used as unique identifiers for program
    operations when constructing BasicBlocks.
    """

  @abc.abstractmethod
  def parse(self) -> typing.Iterable[cfg.BasicBlock]:
    """
    Parses the raw input object and returns an iterable of BasicBlocks.
    """


class EVMBlockParser(BlockParser):
  def __init__(self, dasm:typing.Iterable[str]):
    """
    Parses raw EVM disassembly lines and creates corresponding EVMBasicBlocks.
    This does NOT follow jumps or create graph edges - it just parses the
    disassembly and creates the blocks.

    Args:
      dasm: iterable of raw disasm output lines to be parsed by this instance
    """
    super().__init__(dasm)

    self.__blocks = []

  def parse(self):
    super().parse()

    self._ops = []

    # Construct a list of EVMOp objects from the raw input disassembly
    # lines, ignoring the first line of input (which is the bytecode's hex
    # representation when using Ethereum's disasm tool). Any line which does
    # not produce enough tokens to be valid disassembly after being split() is
    # also ignored.
    for i, l in enumerate(self._raw):
      if len(l.split()) == 1:
        logger.log("Warning (line {}): skipping invalid disassembly:\n   {}"
                    .format(i+1, l.rstrip()))
        continue
      elif len(l.split()) < 1:
        continue
      self._ops.append(self.evm_op_from_dasm(l))

    self.__blocks = []
    self.__create_blocks()

    return self.__blocks

  @staticmethod
  def evm_op_from_dasm(line:str) -> evm_cfg.EVMOp:
    """
    Creates and returns a new EVMOp object from a raw line of disassembly.

    Args:
      line: raw line of output from Ethereum's disasm disassembler.

    Returns:
      evm_cfg.EVMOp: the constructed EVMOp
    """
    l = line.split()
    if len(l) > 3:
      return evm_cfg.EVMOp(int(l[0]), opcodes.opcode_by_name(l[1]), int(l[3], 16))
    elif len(l) > 1:
      return evm_cfg.EVMOp(int(l[0]), opcodes.opcode_by_name(l[1]))
    else:
      raise NotImplementedError("Could not parse unknown disassembly format: " + str(l))

class EVMBytecodeParser(EVMBlockParser):
  def __init__(self, raw:object):
    super().__init__(raw)

    if type(raw) is str:
      raw = bytes.fromhex(raw.replace("0x", ""))
    else:
      raw = bytes(raw)

    self.raw = raw

    self.__pc = 0

  def __consume(self, n):
    bytes_ = self.raw[self.__pc : self.__pc + n]
    self.__pc += n
    return bytes_

  def __has_more_bytes(self):
    return self.__pc < len(self.raw)

  def parse(self):
    super().parse()

    self._ops = []

    while self.__has_more_bytes():
      pc = self.__pc
      byte = int.from_bytes(self.__consume(1), "big")
      op = opcodes.opcode_by_value(byte)
      const, const_size = None, 0

      if op.is_push:
        const_size = op.code - opcodes.PUSH1.code + 1

      if const_size > 0:
        const = self.__consume(const_size)
        const = int.from_bytes(const, "big")

      self._ops.append(evm_cfg.EVMOp(pc, op, const))
