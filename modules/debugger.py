from __future__ import annotations
from .typecheck import *

from .import core, ui

import sublime
import webbrowser
from functools import partial

from .import dap
from .import persistance

from .settings import Settings
from .breakpoints import Breakpoints, SourceBreakpoint
from .project import Project
from .watch import Watch
from .adapters_registry import AdaptersRegistry

from .debugger_console_panel import DebuggerConsoleOutputPanel
from .debugger_main_panel import DebuggerMainOutputPanel
from .debugger_output_panel import DebuggerOutputPanel

from .import util

from .terminal_external import ExternalTerminal, ExternalTerminalTerminus, ExternalTerminalMacDefault, ExternalTerminalWindowsDefault
from .terminal_task import TerminalTask, Tasks
from .terminal_integrated import TerminusIntegratedTerminal

from .source_navigation import SourceNavigationProvider



class Debugger (dap.Debugger, dap.SessionListener):
	
	instances: dict[int, 'Debugger'] = {}
	creating: dict[int, bool] = {}

	@staticmethod
	def create(window: sublime.Window) -> Debugger:
		debugger = Debugger.get(window, True)
		assert debugger
		return debugger

	@staticmethod
	def get(window_or_view: sublime.Window|sublime.View, create: bool = False) -> Debugger|None:
		if isinstance(window_or_view, sublime.View):
			window = window_or_view.window()
		else:
			window = window_or_view

		if window is None:
			return None

		id = window.id()
		instance = Debugger.instances.get(id)

		if not instance and create:
			if Debugger.creating.get(id):
				raise core.Error('We shouldn\'t be creating another debugger instance for this window...')

			Debugger.creating[id] = True
			try:
				instance = Debugger(window)
				Debugger.instances[id] = instance

			except core.Error:
				core.exception()

			Debugger.creating[id] = False

		if instance and create:
			instance.open()

		return instance

	def __init__(self, window: sublime.Window) -> None:
		self.window = window

		self.on_error: core.Event[str] = core.Event()
		self.on_info: core.Event[str] = core.Event()

		self.on_session_added: core.Event[dap.Session] = core.Event()
		self.on_session_removed: core.Event[dap.Session] = core.Event()
		self.on_session_active: core.Event[dap.Session] = core.Event()

		self.on_session_modules_updated: core.Event[dap.Session] = core.Event()
		self.on_session_sources_updated: core.Event[dap.Session] = core.Event()
		self.on_session_variables_updated: core.Event[dap.Session] = core.Event()
		self.on_session_threads_updated: core.Event[dap.Session] = core.Event()
		self.on_session_state_updated: core.Event[dap.Session, dap.Session.State] = core.Event()
		self.on_session_output: core.Event[dap.Session, dap.OutputEvent] = core.Event()
		self.on_session_output: core.Event[dap.Session, dap.OutputEvent] = core.Event()

		self.on_session_run_terminal_requested: core.EventReturning[Awaitable[dap.RunInTerminalResponse], dap.Session, dap.RunInTerminalRequestArguments] = core.EventReturning()
		self.on_session_run_task_requested: core.EventReturning[Awaitable[None], dap.Session|None, dap.TaskExpanded] = core.EventReturning()

		self.session: dap.Session|None = None
		self.sessions: list[dap.Session] = []
		self.disposeables: list[Any] = []
		self.last_run_task = None


		self.output_panels: list[DebuggerOutputPanel] = []
		self.on_output_panels_updated: core.Event[None] = core.Event()

		self.project = Project(window)
		self.run_to_current_line_breakpoint: SourceBreakpoint|None = None

		self.breakpoints = Breakpoints()
		self.watch = Watch()		

		self.disposeables.extend([
			self.project,
			self.breakpoints,
		])

		self.load_data()

		self.project.on_updated.add(self._on_project_or_settings_updated)

		self.source_provider = SourceNavigationProvider(self.project, self)

		self.tasks = Tasks()
		self.disposeables.extend([
			self.tasks,
		])

		self.console = DebuggerConsoleOutputPanel(self)
		self.console.on_input.add(self.on_run_command)
		self.console.on_navigate.add(self._on_navigate_to_source)

		self.panels = DebuggerMainOutputPanel(self)
		self.panels.on_closed = lambda: self.console.open()
		
		self.disposeables.extend([
			self.console,
			self.panels,
		])

		self.external_terminals: dict[dap.Session, list[ExternalTerminal]] = {}
		self.integrated_terminals: dict[dap.Session, list[TerminusIntegratedTerminal]] = {}

		# def on_view_activated(view: sublime.View):
		# 	if self.is_active or self.tasks.is_active():
		# 		return
			
		# 	window = view.window()
		# 	if not view.element() and window and window.active_group() == 0:
		# 		# self.console.close()
		# 		self.dispose_terminals(unused_only=True)
		# self.disposeables.extend([
		# 	core.on_view_activated.add(on_view_activated)
		# ])

		self.on_session_state_updated.add(self._on_session_state_updated)
		self.on_session_active.add(self._on_session_active)
		self.on_session_added.add(self._on_session_added)
		self.on_session_removed.add(self._on_session_removed)
		self.on_session_output.add(self._on_session_output)
		self.on_session_run_terminal_requested.add(self._on_session_run_terminal_requested)
		self.on_session_run_task_requested.add(self._on_session_run_task_requested)
		self.on_info.add(self.console.info)
		self.on_error.add(self.console.error)


		self._refresh_none_debugger_output_panels()

	def _refresh_none_debugger_output_panels(self):
		panels = Settings.integrated_output_panels

		def find_output_panel(name: str):
			for panel in self.output_panels:
				print(panel.output_panel_name)
				if panel.output_panel_name == name:
					return panel

		for panel_name in self.window.panels():
			name = panel_name.replace('output.', '')
			if not name in panels:
				continue

			if not find_output_panel(panel_name):
				panel = panels[name]
				output_panel = DebuggerOutputPanel(self, name, name=panel.get('name'), show_panel=False, show_tabs=True, show_tabs_top=panel.get('position') != 'bottom', create=False)
				self.disposeables.append(output_panel)


	def add_output_panel(self, panel: DebuggerOutputPanel):
		self.output_panels.append(panel)
		self.on_output_panels_updated.post()

	def remove_output_panel(self, panel: DebuggerOutputPanel):
		if panel.is_open():
			self.console.open()

		self.output_panels.remove(panel)
		self.on_output_panels_updated.post()

	async def ensure_installed(self, configurations: list[dap.Configuration]):
		types: list[str] = []
		for configuration in configurations:
			if not configuration.type in types:
				types.append(configuration.type)

		for type in types:
			adapter_configuration = AdaptersRegistry.get(type)
			if not adapter_configuration.installed_version:
				install = 'Debug adapter with type name "{}" is not installed.\n Would you like to install it?'.format(adapter_configuration.type)
				if sublime.ok_cancel_dialog(install, 'Install'):
					await self.install_adapter(adapter_configuration, None)

	@core.schedule
	async def start(self, no_debug: bool = False, args: dict[str, Any]|None = None):
		try:
			if args and 'configuration' in args:
				configuration = args['configuration']
				if isinstance(configuration, str):
					previous_configuration_or_compound = self.project.configuration_or_compound
					self.project.load_configuration(configuration, None)
					if not self.project.configuration_or_compound:
						raise core.Error(f'Unable to find the configuration with the name `{configuration}`')
					
					if self.project.configuration_or_compound != previous_configuration_or_compound:
						core.info('Saving data: configuration selection changed')
						self.save_data()

					configurations = self.project.active_configurations()

				else:
					configurations = [
						dap.Configuration.from_json(args['configuration'], -1)
					]

			else:
				configurations = self.project.active_configurations()
				if not configurations:
					self.console.error('Add or select a configuration to begin debugging')
					await self.change_configuration()

				configurations = self.project.active_configurations()
				if not configurations:
					return

			await self.start_with_configurations(configurations, no_debug)

		except Exception as e:
			core.exception()
			core.display(e)

	@core.schedule
	async def start_with_configurations(self, configurations: list[dap.Configuration], no_debug: bool = False):
		
		# grab variables before we open the console because the console will become the focus
		# and then things like $file would point to the console
		variables = self.project.extract_variables()

		self.dispose_terminals(unused_only=True)

		# clear console if there are not any currently active sessions
		if not self.sessions:
			self.console.clear()
			core.info('cleared console')

		self.console.open()

		await self.ensure_installed(configurations)

		for configuration in configurations:
			@core.schedule
			async def launch(configuration: dap.Configuration):
				try:
					adapter_configuration = AdaptersRegistry.get(configuration.type)
					configuration_expanded = dap.ConfigurationExpanded(configuration, variables)

					pre_debug_task = configuration_expanded.get('pre_debug_task')
					post_debug_task = configuration_expanded.get('post_debug_task')

					if pre_debug_task:
						configuration_expanded.pre_debug_task = dap.TaskExpanded(self.project.get_task(pre_debug_task), variables)

					if post_debug_task:
						configuration_expanded.post_debug_task = dap.TaskExpanded(self.project.get_task(post_debug_task), variables)						

					await self.launch(self.breakpoints, adapter_configuration, configuration_expanded, no_debug=no_debug)
				except core.Error as e:
					if sublime.ok_cancel_dialog("Error Launching Configuration\n\n{}".format(str(e)), 'Open Project'):
						self.project.open_project_configurations_file()

			launch(configuration)

	async def launch(self, breakpoints: Breakpoints, adapter: dap.AdapterConfiguration, configuration: dap.ConfigurationExpanded, restart: Any|None = None, no_debug: bool = False, parent: dap.Session|None = None) -> dap.Session:
		for session in self.sessions:
			if configuration.id_ish == session.configuration.id_ish:
				await self.stop(session)
				# return

		session = dap.Session(
			adapter_configuration=adapter,
			configuration=configuration,
			restart=restart,
			no_debug=no_debug,
			breakpoints=breakpoints, 
			watch=self.watch, 
			listener=self, 
			debugger=self,
			parent=parent,
			log=self.console,
		)

		@core.schedule
		async def run():
			self.add_session(session)

			await session.launch()
			await session.wait()

			self.remove_session(session)
		run()

		return session

	async def on_session_task_request(self, session: dap.Session, task: dap.TaskExpanded):
		response = self.on_session_run_task_requested(session, task)
		if not response: raise core.Error('No run task response')
		return await response

	async def on_session_terminal_request(self, session: dap.Session, request: dap.RunInTerminalRequestArguments) -> dap.RunInTerminalResponse:
		response = self.on_session_run_terminal_requested(session, request)
		if not response: raise core.Error('No terminal session response')
		return await response

	def on_session_state_changed(self, session: dap.Session, state: dap.Session.State):
		self.on_session_state_updated(session, state)

	def on_session_selected_frame(self, session: dap.Session, frame: dap.StackFrame|None):
		self.session = session
		self.on_session_state_updated(session, session.state)
		self.on_session_active(session)

	def on_session_output_event(self, session: dap.Session, event: dap.OutputEvent):
		self.on_session_output(session, event)

	def on_session_updated_modules(self, session: dap.Session):
		self.on_session_modules_updated(session)

	def on_session_updated_sources(self, session: dap.Session):
		self.on_session_sources_updated(session)

	def on_session_updated_variables(self, session: dap.Session):
		self.on_session_variables_updated(session)

	def on_session_updated_threads(self, session: dap.Session):
		self.on_session_threads_updated(session)

	def add_session(self, session: dap.Session):
		self.sessions.append(session)
		# if a session is added select it
		self.session = session

		self.on_session_added(session)
		self.on_session_active(session)

	def remove_session(self, session: dap.Session):
		self.sessions.remove(session)
		session.dispose()

		if self.session == session:
			self.session = self.sessions[0] if self.sessions else None
		
			# try to select the first session with threads if there is one
			for session in self.sessions:
				if session.threads:
					self.session = session
					break

			self.on_session_active(session)

		self.on_session_state_updated(session, dap.Session.State.STOPPED)
		self.on_session_removed(session)


	@core.schedule
	async def resume(self) -> None:
		try: await self.active.resume()
		except core.Error as e: self.console.error(f'Unable to continue: {e}')

	@core.schedule
	async def pause(self) -> None:
		try: await self.active.pause()
		except core.Error as e: self.console.error(f'Unable to pause: {e}')

	@core.schedule
	async def step_over(self) -> None:
		try: await self.active.step_over()
		except core.Error as e: self.console.error(f'Unable to step over: {e}')

	@core.schedule
	async def step_in(self) -> None:
		try: await self.active.step_in()
		except core.Error as e: self.console.error(f'Unable to step in: {e}')

	@core.schedule
	async def step_out(self) -> None:
		try: await self.active.step_out()
		except core.Error as e: self.console.error(f'Unable to step out: {e}')

	@core.schedule
	async def stop(self, session: dap.Session|None = None) -> None:
		# the stop command stops all sessions in a hierachy
		try: 
			if not session:
				root = self.active
				while root.parent:
					root = root.parent

				self.stop(root)
				return

			session_stop = session.stop()
			for child in session.children:
				self.stop(child)
			
			await session_stop

		except core.Error as e: self.console.error(f'Unable to stop: {e}')

	@property
	def is_active(self):
		return self.session != None

	@property
	def active(self):
		if not self.session:
			raise core.Error('No Active Debug Sessions')
		return self.session

	@active.setter
	def active(self, session: dap.Session):
		self.session = session
		self.on_session_state_updated(session, session.state)
		self.on_session_active(session)

	def clear_all_breakpoints(self):
		self.breakpoints.data.remove_all()
		self.breakpoints.source.remove_all()
		self.breakpoints.function.remove_all()

	def dispose(self) -> None:
		self.save_data()

		self.dispose_terminals()

		for session in self.sessions:
			session.dispose()
		for d in self.disposeables:
			d.dispose()

		del Debugger.instances[self.window.id()]

	def is_paused(self):
		return self.is_active and self.active.state == dap.Session.State.PAUSED

	def is_running(self):
		return self.is_active and self.active.state == dap.Session.State.RUNNING

	def is_stoppable(self):
		return self.is_active and self.active.state != dap.Session.State.STOPPED

	def run_to_current_line(self) -> None:
		if self.run_to_current_line_breakpoint:
			self.breakpoints.source.remove(self.run_to_current_line_breakpoint)

		file, line, column = self.project.current_file_line_column()
		self.run_to_line_breakpoint = self.breakpoints.source.add_breakpoint(file, line, column)

	def load_data(self):
		json = persistance.load(self.project.project_name)
		self.project.load_from_json(json.get('project', {}))
		self.breakpoints.load_from_json(json.get('breakpoints', {}))
		self.watch.load_json(json.get('watch', []))

	def save_data(self):
		json = {
			'project': self.project.into_json(),
			'breakpoints': self.breakpoints.into_json(),
			'watch': self.watch.into_json(),
		}
		persistance.save(self.project.project_name, json)

	def on_run_task(self) -> None:
		values: list[ui.InputListItem] = []
		for task in self.project.tasks:
			def run(task: dap.Task = task):
				self.last_run_task = task
				self.run_task(task)

			values.append(ui.InputListItem(run, task.name))

		ui.InputList(values, 'Select task to run').run()

	def on_run_last_task(self) -> None:
		if self.last_run_task:
			self.run_task(self.last_run_task)
		else:
			self.on_run_task()

	@core.schedule
	async def run_task(self, task: dap.Task):
		self.dispose_terminals(unused_only=True)
		variables = self.project.extract_variables()
		await self.on_session_run_task_requested(None, dap.TaskExpanded(task, variables))

	def refresh_phantoms(self) -> None:
		ui.Layout.render_layouts()

	@core.schedule
	async def on_run_command(self, command: str) -> None:
		try: 
			result = await self.active.evaluate_expression(command, context='repl')
			if result.variablesReference:
				self.console.write(f'', 'blue', ensure_new_line=True)
				self.console.write_variable(dap.Variable.from_evaluate(self.active, '', result), self.console.at())
			elif result.result:
				self.console.write(result.result, 'blue', ensure_new_line=True)
			else:
				core.debug('discarded evaluated expression empty result')

		except core.Error as e:
			self.console.error(f'{e}')

	@core.schedule
	async def evaluate_selected_expression(self):
		if view := sublime.active_window().active_view():
			sel = view.sel()[0]
			expression = view.substr(sel) 
			self.on_run_command(expression)

	def toggle_breakpoint(self):
		file, line, _ = self.project.current_file_line_column()
		self.breakpoints.source.toggle(file, line)

	def toggle_column_breakpoint(self):
		file, line, column = self.project.current_file_line_column()
		self.breakpoints.source.toggle(file, line, column)

	def add_function_breakpoint(self):
		self.breakpoints.function.add_command()

	def add_watch_expression(self):
		self.watch.add_command()

	def on_input_command(self) -> None:
		self.console.open()
		self.console.set_input_mode()

	def _on_project_or_settings_updated(self):
		for panel in self.output_panels:
			panel.update_settings()

	def _on_session_active(self, session: dap.Session):
		if not self.is_active:
			self.source_provider.clear()
			return

		active_session = self.active
		thread = active_session.selected_thread
		frame = active_session.selected_frame

		if thread and frame and frame.source:
			self.source_provider.select_source_location(dap.SourceLocation(frame.source, frame.line, frame.column), thread)
		else:
			self.source_provider.clear()

	def _on_session_added(self, sessions: dap.Session):
		self.console.open()

	def _on_session_removed(self, sessions: dap.Session):

		# if the debugger panel is open switch to the console. We could be on a pre debug step panel which we want to remain on.
		if self.panels.is_open():
			self.console.open()

		if not self.is_active:
			self.console.info('Debugging ended')

	def _on_session_state_updated(self, session: dap.Session, state: dap.Session.State):
		if self.is_active and self.active != session:
			return

		if state == dap.Session.State.PAUSED:
			self.window.bring_to_front()
			# util.bring_sublime_text_to_front()

			if session.stepping:
				...
			else:
				self.panels.middle_panel.select(self.panels.callstack_panel)
				self.panels.open()

		if state == dap.Session.State.RUNNING:
			if not session.stepping:
				if terminals := self.integrated_terminals.get(session):
					terminals[0].open()
				else:
					self.console.open()

	def _on_session_output(self, session: dap.Session, event: dap.OutputEvent) -> None:
		self.console.program_output(session, event)

	async def _on_session_run_task_requested(self, session: dap.Session|None, task: dap.TaskExpanded) -> None:
		await self.tasks.run(self, task)

	async def _on_session_run_terminal_requested(self, session: dap.Session, request: dap.RunInTerminalRequestArguments) -> dap.RunInTerminalResponse:
		title = request.title or session.configuration.name
		env = request.env or {}
		cwd = request.cwd
		commands = request.args

		if request.kind == 'external':
			def external_terminal():
				if self.project.external_terminal_kind == 'platform':
					if core.platform.osx:
						return ExternalTerminalMacDefault(title, cwd, commands, env)
					elif core.platform.windows:
						return ExternalTerminalWindowsDefault(title, cwd, commands, env)
					elif core.platform.linux:
						raise core.Error('default terminal for linux not implemented')
					else:
						raise core.Error('unreachable')

				if self.project.external_terminal_kind == 'terminus':
					return ExternalTerminalTerminus(title, cwd, commands, env)
				
				raise core.Error('unknown external terminal type "{}"'.format(self.project.external_terminal_kind))

			terminal = external_terminal()
			self.external_terminals.setdefault(session, []).append(terminal)
			return dap.RunInTerminalResponse(processId=None, shellProcessId=None) 

		if request.kind == 'integrated':
			terminal = TerminusIntegratedTerminal(self, request.title or 'Untitled', request.cwd, request.args, request.env)
			self.integrated_terminals.setdefault(session, []).append(terminal)

			return dap.RunInTerminalResponse(processId=None, shellProcessId=None)

		raise core.Error('unknown terminal kind requested "{}"'.format(request.kind))

	def dispose_terminals(self, unused_only: bool=False):
		removed_sessions: list[dap.Session] = []

		for session, terminals in self.integrated_terminals.items():
			if not unused_only or session.state == dap.Session.State.STOPPED:
				removed_sessions.append(session)
				for terminal in terminals:
					terminal.dispose()

		for session, terminals in self.external_terminals.items():
			if not unused_only or session.state == dap.Session.State.STOPPED:
				removed_sessions.append(session)
				for terminal in terminals:
					terminal.dispose()

		for session in removed_sessions:
			try: del self.external_terminals[session]
			except KeyError:...

			try: del self.integrated_terminals[session]
			except KeyError:...

		self.tasks.remove_finished()

	def is_open(self):
		for panel in self.output_panels:
			if panel.is_open():
				return True
		return False
	
	def open(self) -> None:
		if not self.is_active:
			self.open_console()
		else:
			self.open_panels()

	def open_panels(self) -> None:
		self.panels.open()
		self.panels.middle_panel.select(self.panels.callstack_panel)

	def open_console(self) -> None:
		self.console.open()

	def _on_navigate_to_source(self, source: dap.SourceLocation):
		self.source_provider.show_source_location(source)



	# Configuration Stuff
	def set_configuration(self, configuration: Union[dap.Configuration, dap.ConfigurationCompound]):
		self.project.configuration_or_compound = configuration
		self.save_data()

	async def change_configuration_input_items(self) -> list[ui.InputListItem]:
		values: list[ui.InputListItem] = []
		for c in self.project.compounds:
			name = f'{c.name}\tcompound'
			values.append(ui.InputListItemChecked(partial(self.set_configuration, c), c == self.project.configuration_or_compound, name))

		for c in self.project.configurations:
			name = f'{c.name}\t{c.type}'
			values.append(ui.InputListItemChecked(partial(self.set_configuration, c), c == self.project.configuration_or_compound, name))

		if values:
			values.append(ui.InputListItem(lambda: ..., ""))

		values.append(ui.InputListItem(lambda: self.add_configuration(), 'Add Configuration'))
		values.append(ui.InputListItem(lambda: self.project.open_project_configurations_file(), 'Edit Configuration File'))
		values.append(ui.InputListItem(lambda: self.install_adapters(), 'Install Adapters'))
		return values

	@core.schedule
	async def on_settings(self) -> None:
		def about():
			webbrowser.open_new_tab('https://github.com/daveleroy/sublime_debugger#getting-started')

		def report_issue():
			webbrowser.open_new_tab('https://github.com/daveleroy/sublime_debugger/issues')

		values = await self.change_configuration_input_items()

		values.extend([
			ui.InputListItem(lambda: ..., ''),
			ui.InputListItem(report_issue, 'Report Issue', kind=(sublime.KIND_ID_AMBIGUOUS, '⧉', '')),
			ui.InputListItem(about, 'About/Getting Started', kind=(sublime.KIND_ID_AMBIGUOUS, '⧉', '')),
		])

		ui.InputList(values).run()

	@core.schedule
	async def change_configuration(self) -> None:
		await ui.InputList(await self.change_configuration_input_items(), 'Add or Select Configuration').run()

	@core.schedule
	async def add_configuration(self) -> None:
		items = self.add_configuration_snippet_adapters_list_items()
		return await ui.InputList(items, 'Add Debug Configuration').run()

	@core.schedule
	async def install_adapters(self) -> None:
		self.console.open()
		items = await self.install_adapters_list_items()
		await ui.InputList(items, 'Install/Update Debug Adapters').run()

	@core.schedule
	async def install_adapter(self, adapter: dap.AdapterConfiguration, version: str|None) -> None:
		self.console.log('info', f'[Installing {adapter.type}]')
		try:
			await adapter.installer.install(version, self.console)

		except Exception as error:
			self.console.error((str(error)))
			self.console.error(f'[Unable to install {adapter.type}]')
			raise error

		AdaptersRegistry.recalculate_schema()
		self.console.log('success', f'[Successfully installed {adapter.type}]')

	async def install_adapters_list_items(self):
		self.console.log('group-start', '[Checking For Updates]')

		installed: list[Awaitable[ui.InputListItem]] = []
		not_installed: list[Awaitable[ui.InputListItem]] = []

		for adapter in AdaptersRegistry.all:
			if not Settings.development and adapter.development:
				continue

			async def item(adapter: dap.AdapterConfiguration) -> ui.InputListItem:
				name = adapter.type
				installed_version = adapter.installed_version

				versions: list[str] = []
				if installer := adapter.installer:
					try:
						versions = await installer.installable_versions(self.console)
					except Exception as e:
						core.error(f'Unable to fetch instaled version: {e}')

				if adapter.development:
					name += ' (dev)'

				if installed_version:
					if versions and versions[0] != installed_version:
						name += f'\tUpdate Available {installed_version} → {versions[0]}'
						self.console.log('warn', f'{adapter.type}: Update Available {installed_version} → {versions[0]}')
					else:
						name += f'\t{installed_version}'

				def input_list():
					items = [
						ui.InputListItem(partial(self.install_adapter, adapter, version), version) 
						for version in versions
					]
					if installer := adapter.installer:
						if installed_version:
							items.append(ui.InputListItem(lambda: installer.uninstall(), 'Uninstall'))

					return ui.InputList(items, 'Choose version to install')

				if installed_version:
					return ui.InputListItemChecked(
						lambda: self.install_adapter(adapter, versions[0]),
						installed_version != None,
						name,
						run_alt=input_list(),
						details=f'<a href="{adapter.docs}">documentation</a>'
					)
				else:
					return ui.InputListItemChecked(
						input_list(),
						installed_version != None,
						name,
						details=f'<a href="{adapter.docs}">documentation</a>'
					)

			if adapter.installed_version:
				installed.append(item(adapter))
			else:
				not_installed.append(item(adapter))
			
		items = list(await core.gather(*(installed + not_installed)))
		self.console.log('group-end', '[Finished]')
		return items

	def add_configuration_snippet_adapters_list_items(self):
		def insert(snippet: Any):
			insert = snippet.get('body', '{ error: no body field }')
			core.run(AdaptersRegistry._insert_snippet(sublime.active_window(), insert))

		installed: list[ui.InputListItem] = []
		not_installed: list[ui.InputListItem] = []

		for adapter in AdaptersRegistry.all:
			if not Settings.development and adapter.development:
				continue

			def item(adapter: dap.AdapterConfiguration) -> ui.InputListItem:
				name = adapter.type
				installed_version = adapter.installed_version
		
				if installed_version:
					snippet_input_items: list[ui.InputListItem] = []

					for snippet in adapter.configuration_snippets or []:
						type = snippet.get('body', {}).get('request', '??')
						snippet_input_items.append(ui.InputListItem(partial(insert, snippet), snippet.get('label', 'label'), details=type))

					subtitle = f'{len(snippet_input_items)} Snippets' if len(snippet_input_items) != 1 else '1 Snippet'

					return ui.InputListItemChecked(
						ui.InputList(snippet_input_items, 'choose a snippet to insert'),
						installed_version != None,
						name + '\t' + subtitle,
						details= f'<a href="{adapter.docs}">documentation</a>'
					)
				else:
					return ui.InputListItemChecked(
						lambda: self.install_adapter(adapter, None),
						installed_version != None,
						name,
						details=f'<a href="{adapter.docs}">documentation</a>'
					)

			if adapter.installed_version:
				installed.append(item(adapter))
			else:
				not_installed.append(item(adapter))
			
		return installed + not_installed
