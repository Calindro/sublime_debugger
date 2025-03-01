from __future__ import annotations

from .adapters_registry import AdaptersRegistry
from .settings import SettingsRegistery
from .typecheck import *

from .debugger import Debugger
from .command import Command, CommandDebugger, CommandsRegistry, open_settings

class Commands:
	
	# if you add any commands use this command to regenerate any .sublime-menu files
	# this command also regenerates the LSP-json package.json file for any installed adapters
	generate_commands = Command(
		name='Generate Commands/Settings/Schema',
		action=lambda _: (CommandsRegistry.generate_commands_and_menus(), AdaptersRegistry.recalculate_schema(), SettingsRegistery.generate_settings()),
		flags=Command.menu_commands
	)

	open = CommandDebugger (
		name='Open',
		action=lambda debugger: debugger.open(),
	)
	quit = CommandDebugger (
		name='Quit',
		action=lambda debugger: debugger.dispose(),
		flags=Command.menu_commands|Command.menu_main|Command.visible_debugger_open,
	)
	settings = Command(
		name='Settings',
		action=open_settings,
		flags=Command.menu_main
	)
	settings = Command(
		name='Preferences: Debugger Settings',
		action=open_settings,
		flags=Command.menu_commands | Command.menu_no_prefix
	)

	install_adapters = CommandDebugger (
		name='Install Adapters',
		action=lambda debugger: debugger.install_adapters()
	)
	change_configuration = CommandDebugger (
		name='Add or Select Configuration',
		action=lambda debugger: debugger.change_configuration()
	)
	
	add_configuration = CommandDebugger (
		name='Add Configuration',
		action=lambda debugger: debugger.add_configuration()
	)
	
	# - 

	start = CommandDebugger (
		name='Start',
		action_with_arguments=lambda debugger, args: debugger.start(False, args),
		flags=Command.menu_commands|Command.menu_main|Command.open_without_running|Command.section_start
	)
	open_and_start: CommandDebugger = CommandDebugger (
		name='Open and Start',
		action_with_arguments=lambda debugger, args: debugger.start(False, args),
		flags=0
	)
	start_no_debug = CommandDebugger (
		name='Start (no debug)',
		action=lambda debugger: debugger.start(True),
	)
	stop = CommandDebugger (
		name='Stop',
		action=lambda debugger: debugger.stop(), #type: ignore
		enabled=Debugger.is_stoppable
	)

	continue_ = CommandDebugger (
		name='Continue',
		action=lambda debugger: debugger.resume(),
		enabled=Debugger.is_paused
	)
	pause = CommandDebugger (
		name='Pause',
		action=lambda debugger: debugger.pause(),
		enabled=Debugger.is_running,
	)
	step_over = CommandDebugger (
		name='Step Over',
		action=lambda debugger: debugger.step_over(),
		enabled=Debugger.is_paused
	)
	step_in = CommandDebugger (
		name='Step In',
		action=lambda debugger: debugger.step_in(),
		enabled=Debugger.is_paused
	)
	step_out = CommandDebugger (
		name='Step Out',
		action=lambda debugger: debugger.step_out(),
		enabled=Debugger.is_paused
	)

	# -

	input_command = CommandDebugger (
		name='Input Command',
		action=lambda debugger: debugger.on_input_command(),
		flags=Command.section_start
		# enabled=Debugger.is_active
	)
	run_task = CommandDebugger (
		name='Run Task',
		action=Debugger.on_run_task,
	)
	run_last_task = CommandDebugger (
		name='Run Last Task',
		action=Debugger.on_run_last_task,
		flags=Command.menu_main,
	)
	add_function_breakpoint = CommandDebugger (
		name='Add Function Breakpoint',
		action=lambda debugger: debugger.add_function_breakpoint(),
	)
	clear_breakpoints = CommandDebugger (
		name='Clear Breakpoints',
		action=Debugger.clear_all_breakpoints,
		flags=Command.menu_widget|Command.menu_commands|Command.menu_main,
	)
	clear_console = CommandDebugger (
		name='Clear Console',
		action=lambda debugger: debugger.console.clear(),
		flags=Command.menu_widget|Command.menu_commands|Command.menu_main,
	)
	show_protocol = CommandDebugger (
		name='Show Protocol',
		action=lambda debugger: debugger.console.protocol.open(),
		flags=Command.menu_widget|Command.menu_commands|Command.menu_main,
	)
	add_watch_expression = CommandDebugger (
		name='Add Watch Expression',
		action=lambda debugger: debugger.add_watch_expression(),
	)
	save_data = CommandDebugger (
		name='Force Save',
		action=Debugger.save_data,
	)

	# - 

	toggle_breakpoint = CommandDebugger (
		name='Toggle Breakpoint',
		action=lambda debugger: debugger.toggle_breakpoint(),
		flags=Command.menu_context,
	)
	toggle_column_breakpoint = CommandDebugger (
		name='Toggle Column Breakpoint',
		action=lambda debugger: debugger.toggle_column_breakpoint(),
		flags=Command.menu_context,
	)
	run_to_current_line = CommandDebugger (
		name='Run To Selected Line',
		action=Debugger.run_to_current_line,
		enabled=Debugger.is_paused,
		flags=Command.menu_context,
	)
