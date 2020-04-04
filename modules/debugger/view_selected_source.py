from .. typecheck import *
from .. import core, ui, dap
from .views.selected_line import SelectedLine

from .debugger_sessions import DebuggerSessions
from .debugger_project import DebuggerProject

import sublime
import sublime_plugin

class DebuggerShowLineCommand(sublime_plugin.TextCommand):
	def run(self, edit, line: int, move_cursor: bool): #type: ignore
		a = self.view.text_point(line, 0)
		region = sublime.Region(a, a)
		self.view.show_at_center(region)
		if move_cursor:
			self.view.sel().clear()
			self.view.sel().add(region)

class DebuggerReplaceContentsCommand(sublime_plugin.TextCommand):
	def run(self, edit, characters):
		self.view.replace(edit, sublime.Region(0, self.view.size()), characters)
		self.view.sel().clear()

class ViewSelectedSourceProvider:
	def __init__(self, project: DebuggerProject, sessions: DebuggerSessions):
		self.sessions = sessions
		self.project = project
		self.updating = None #type: Optional[Any]
		self.generated_view = None #type: Optional[sublime.View]
		self.selected_frame_line = None #type: Optional[SelectedLine]

	def select(self, source: dap.Source, line: int, stopped_reason: str):
		if self.updating:
			self.updating.cancel()
		def on_error(error):
			if error is not core.CancelledError:
				core.log_error(error)

		async def select_async(source: dap.Source, line: int, stopped_reason: str):
			self.clear_selected()
			view = await self.navigate_to_source(source, line)
			self.selected_frame_line = SelectedLine(view, line, stopped_reason)

		self.updating = core.run(select_async(source, line, stopped_reason), on_error=on_error)

	def navigate(self, source: dap.Source, line: int = 1):
		if self.updating:
			self.updating.cancel()

		def on_error(error):
			if error is not core.CancelledError:
				core.log_error(error)

		async def navigate_async(source: dap.Source, line: int):
			self.clear_generated_view()
			await self.navigate_to_source(source, line, move_cursor=True)

		self.updating = core.run(navigate_async(source, line), on_error=on_error)

	def clear(self):
		if self.updating:
			self.updating.cancel()

		self.clear_selected()
		self.clear_generated_view()

	def clear_selected(self):
		if self.selected_frame_line:
			self.selected_frame_line.dispose()
			self.selected_frame_line = None

	def clear_generated_view(self):
		if self.generated_view:
			self.generated_view.close()
			self.generated_view = None

	def dispose(self):
		self.clear()

	async def navigate_to_source(self, source: dap.Source, line: int, move_cursor: bool = False) -> sublime.View:
		

		# if we aren't going to reuse the previous generated view
		# or the generated view was closed (no buffer) throw it away
		if not source.sourceReference or self.generated_view and not self.generated_view.buffer_id():
			self.clear_generated_view()

		if source.sourceReference:
			session = self.sessions.active
			content = await session.client.GetSource(source)

			view = self.generated_view or self.project.window.new_file()
			self.generated_view = view
			view.set_name(source.name or "")
			view.set_read_only(False)
			view.run_command('debugger_replace_contents', {
				'characters': content
			})
			view.set_read_only(True)
			view.set_scratch(True)
		elif source.path:
			view = await core.sublime_open_file_async(self.project.window, source.path)
		else:
			raise core.Error('source has no reference or path')

		await core.wait_for_view_to_load(view)
		# @FIXME why does running debugger_show_line right away not work for views that are not already open? We waited for the view to be loaded
		await core.sleep(0.15)
		view.run_command("debugger_show_line", {
			'line': line - 1,
			'move_cursor': move_cursor
		})
		return view
