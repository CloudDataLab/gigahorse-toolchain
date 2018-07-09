"""exporter.py: abstract classes for exporting facts"""

import abc
import csv
import logging
import os

import src.opcodes as opcodes


class Exporter(abc.ABC):
    generate_dl = False
    def __init__(self, source: object):
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


class InstructionTsvExporter(Exporter):
    """
    Prints a textual representation of the given CFG to stdout.

    Args:
      cfg: source CFG to be printed.
      ordered: if True (default), print BasicBlocks in order of entry.
    """


    def __init__(self, blocks, ordered: bool = True):
        self.ordered = ordered
        self.blocks = []
        self.blocks = blocks

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
    def get_file_handle(self):
        if self.generate_dl:
            return open('decompiler_inputs.dl', 'w')
        else:
            return open('/tmp/tmp', 'w')

    def export(self, output_dir = ""):
        """
        Print basic block info to tsv.
        """
        if output_dir != "":
            os.makedirs(output_dir, exist_ok=True)

        def generate(filename, entries):
            path = os.path.join(output_dir, filename)

            with open(path, 'w') as f:
                writer = csv.writer(f, delimiter='\t', lineterminator='\n')
                writer.writerows(entries)
        f=self.get_file_handle()

        statements = {'MISSING': []}
        for k, opcode in opcodes.OPCODES.items():
            statements[k] = []
            if opcode.is_push():
                f.write('.decl %s(stmt: Statement, value: Value)\n'%k)
            else:
                f.write('.decl %s(stmt: Statement)\n'%k)
            f.write('.input %s\n'%k)
            f.write('\n')
        instructions = []
        instructions_order = []
        for block in self.blocks:
            for op in block.evm_ops:
                instructions_order.append(int(op.pc))
                instructions.append((hex(op.pc), op.opcode.name))
                if op.opcode.is_push():
                    statements[op.opcode.name].append((hex(op.pc), hex(op.value)))
                else:
                    statements[op.opcode.name].append((hex(op.pc),))

        for k, v in statements.items():
            generate(k+'.facts', v)

        instructions_order = list(map(hex, sorted(instructions_order)))
        generate('Statement_Next.facts', zip(instructions_order, instructions_order[1:]))

        generate('Statement_Opcode.facts', instructions)
                    
        opcode_output = {'alters_flow':bool, 'halts':bool, 'is_arithmetic':bool,
                         'is_call':bool, 'is_dup':bool, 'is_invalid':bool,
                         'is_log':bool, 'is_memory':bool, 'is_missing':bool,
                         'is_push':bool, 'is_storage':bool, 'is_swap':bool,
                         'log_len':int, 'possibly_halts':bool, 'push_len':int,
                         'stack_delta':int, 'pop_words':int, 'push_words':int,
                         'ord':int
        }
        
        opcode_key = 'name'
        for prop, typ in opcode_output.items():
            relname = ''.join(map(lambda a : a[0].upper()+ a[1:], ('opcode_'+prop).split('_')))
            if typ == bool:
                f.write('.decl %s(instruction: Opcode)\n'%relname)
            elif typ == int:
                f.write('.decl %s(instruction: Opcode, n: number)\n'%relname)
            else:
                raise NotImplementedError('')
            f.write('.input %s\n'%relname)
            f.write('\n')
            opcode_property = []
            for k, opcode in opcodes.OPCODES.items():
                prop_val = getattr(opcode, prop)()
                if typ is bool and prop_val:
                    opcode_property.append((getattr(opcode, opcode_key), ))
                if typ is int:
                    opcode_property.append((getattr(opcode, opcode_key), prop_val))
                generate(relname +'.facts', opcode_property)
