from cfglib import *
from lattice import *

def block_stack_delta(block:BasicBlock):
	delta = 0

	for line in block.lines:
		delta += line.opcode.stack_delta()

	return delta

def run_analysis(cfg:ControlFlowGraph):
	# Stack size information per block at entry and exit points.
	entry_info = {block: TOP for block in cfg.blocks}
	exit_info = {block: TOP for block in cfg.blocks}
	block_deltas = {block: IntLatticeElement(block_stack_delta(block)) for block in cfg.blocks}

	# Add a distinguished start block which does nothing.
	start_block = BasicBlock()
	cfg.root.parents.append(start_block)
	exit_info[start_block] = IntLatticeElement(0)

	# Find the fixed point that is the meet-over-paths solution
	queue = list(cfg.blocks)

	while queue:
		current = queue.pop()

		# Calculate the new entry value for the current block.
		new_entry = meet_all([exit_info[parent] for parent in current.parents])

		# If the entry value changed, we have to recompute
		# its exit value, and the entry value for its children, eventually.
		if new_entry != entry_info[current]:
			entry_info[current] = new_entry
			exit_info[current] = new_entry + block_deltas[current]
			queue += current.children

	# Remove the start block that was added.
	cfg.root.parents.pop()

	return (entry_info, exit_info)
