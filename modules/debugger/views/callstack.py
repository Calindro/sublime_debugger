from ...typecheck import*
from ...import ui
from ...import core
from ...import dap

from ..debugger_session import DebuggerSession, Thread
from ..debugger_sessions import DebuggerSessions

from .layout import callstack_panel_width
from . import css

import os


class State:
	def __init__(self):
		self._expanded = {}

	def is_expanded(self, item: Any):
		return self._expanded.get(id(item)) is not None

	def set_expanded(self, item: Any, value: bool):
		if value:
			self._expanded[id(item)] = True
		else:
			del self._expanded[id(item)]

	def toggle_expanded(self, item: Any):
		if self.is_expanded(item):
			del self._expanded[id(item)]
		else:
			self._expanded[id(item)] = True


class CallStackView (ui.div):
	def __init__(self, sessions: DebuggerSessions):
		super().__init__()
		self.sessions = sessions
		self.state = State()

	def added(self, layout: ui.Layout):
		self.on_updated = self.sessions.on_updated_threads.add(self.on_threads_updated)

	def removed(self):
		self.on_updated.dispose()

	def on_threads_updated(self, session: DebuggerSession):
		self.dirty()


	def render(self) -> ui.div.Children:
		thread_views = []
		show_session_name = len(self.sessions.sessions) > 1

		for session in self.sessions:
			threads = session.threads
			show_thread_name = len(threads) > 1

			if show_session_name:
				thread_views.append(ui.div(height=css.row_height)[
					ui.text(session.name, css=css.label_secondary)
				])
			for thread in threads:
				is_selected = session == self.sessions.selected_session and session.selected_thread == thread
				if is_selected:
					self.state.set_expanded(thread, True)

				thread_views.append(ThreadView(session, thread, is_selected, self.state, show_thread_name))

		if not thread_views:
			thread_views.append(ui.div(height=css.row_height)[
				ui.text('No Active Debug Sessions', css=css.label_secondary)
			])
		return thread_views

class ThreadView (ui.div):
	def __init__(self, session: DebuggerSession, thread: Thread, is_selected: bool, state: State, show_thread_name: bool):
		super().__init__()
		self.session = session
		self.is_selected = is_selected
		self.show_thread_name = show_thread_name
		self.thread = thread
		self.state = state
		self.frames = [] #type: List[dap.StackFrame]
		self.fetch()

	def added(self, layout: ui.Layout):
		self.on_updated = self.session.on_updated_threads.add(self.dirty)

	def removed(self):
		self.on_updated.dispose()

	@property
	def is_expanded(self):
		return self.state.is_expanded(self.thread) or not self.show_thread_name

	def toggle_expanded(self):
		self.state.toggle_expanded(self.thread)

	@core.schedule
	async def fetch(self):
		if not self.is_expanded or not self.thread.stopped:
			return []

		self.frames = await self.thread.children()
		self.dirty()

	def toggle_expand(self):
		self.toggle_expanded()
		self.fetch()
		self.dirty()

	def on_select_thread(self):
		self.session.set_selected(self.thread, None)

	def on_select_frame(self, frame: dap.StackFrame):
		self.session.set_selected(self.thread, frame)

	def render(self) -> ui.div.Children:
		width = callstack_panel_width(self.layout)
		expandable = self.thread.has_children()
		is_expanded = self.is_expanded

		if expandable:
			thread_item = ui.div(height=css.row_height, width=width)[
				ui.click(self.toggle_expand)[
					ui.icon(ui.Images.shared.open if is_expanded else ui.Images.shared.close),
				],
				ui.click(self.on_select_thread)[
					ui.span(height=1.0, css=css.button)[
						ui.icon(ui.Images.shared.thread_running),
					],
					ui.text(self.thread.name, css=css.label_padding),
					ui.text(self.thread.stopped_reason, css=css.label_secondary),
				],
			]
		else:
			thread_item = ui.div(height=css.row_height, width=width)[
				ui.icon(ui.Images.shared.loading),
				ui.click(self.on_select_thread)[
					ui.span(height=1.0, css=css.button)[
						ui.icon(ui.Images.shared.thread_running),
					],
					ui.text(self.thread.name, css=css.label_padding),
					ui.text(self.thread.stopped_reason, css=css.label_secondary),
				],
			]

		if self.is_selected and not self.session.selected_frame:
			thread_item.add_class(css.selected.class_name)

		if not self.show_thread_name:
			thread_item = ui.div()

		if is_expanded:
			return [
				thread_item,
				ui.div()[
					[StackFrameComponent(self.session, frame, self.is_selected and self.session.selected_frame == frame, lambda frame=frame: self.on_select_frame(frame), width=width) for frame in self.frames] #type: ignore
				]
			]
		else:
			return thread_item


class StackFrameComponent (ui.div):
	def __init__(self, session: DebuggerSession, frame: dap.StackFrame, is_selected: bool, on_click: Callable[[], None], width: float) -> None:
		super().__init__(width=width)
		self.frame = frame
		self.on_click = on_click

		if is_selected:
			self.add_class(css.selected.class_name)

	def render(self) -> ui.div.Children:
		frame = self.frame
		name = os.path.basename(frame.file)
		if frame.presentation == dap.StackFrame.subtle:
			label_padding = css.label_secondary_padding
		else:
			label_padding = css.label_padding

		line_str = str(frame.line)
		file_and_line = ui.click(self.on_click)[
			ui.span(css=css.button)[
				ui.text(line_str, css=css.label),
			],
			# this width calcualtion is annoying ...
			ui.text_align(self._width - css.table_inset.padding_width - css.panel_padding - css.label.padding_width - len(line_str) - css.button.padding_width, [
				ui.text(name, css=label_padding),
				ui.text(frame.name, css=css.label_secondary),
			])
		]

		return [
			ui.div(height=css.row_height, css=css.icon_sized_spacer)[
				file_and_line,
			]
		]
