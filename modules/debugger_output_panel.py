from __future__ import annotations
from typing import TYPE_CHECKING, Callable, Any, ClassVar, Dict

import sublime
import sublime_plugin

from .import core
from .import ui

from .views.debugger_panel import DebuggerActionsTab
from .views import css
from .settings import Settings

if TYPE_CHECKING:
	from .debugger import Debugger

class DebuggerPanelTabs(ui.span):
	def __init__(self, debugger: Debugger, panel: DebuggerOutputPanel):
		super().__init__()
		self.debugger = debugger
		self.debugger.on_output_panels_updated.add(self.dirty)
		self.output_name = panel.output_panel_name
		self.show_tabs_top = panel.show_tabs_top

	def __repr__(self) -> str:
		return super().__repr__() + self.output_name + str(self.children)

	def render(self):
		items: list[ui.span] = []
		
		for panel in self.debugger.output_panels:
			if panel.output_panel_name == self.output_name:
				csss = css.tab_selected
			else:
				csss = css.tab

			name = panel.name

			status = None
			if status_image := panel.status:
				status = ui.click(lambda panel=panel: panel.open_status()) [
					ui.icon(status_image)
				]

			items.append(ui.click(lambda panel=panel: panel.open())[ui.span(css=csss)[
				ui.spacer(1),
				ui.text(name, css=css.label_secondary),
				ui.spacer(1),
				status
			]])

			items.append(ui.spacer(1))

		return items

class DebuggerConsoleTabs(ui.div):
	def __init__(self, debugger: Debugger, panel: DebuggerOutputPanel):
		super().__init__(css=css.console_tabs_top if panel.show_tabs_top else css.console_tabs_bottom)
		self.debugger_actions = DebuggerActionsTab(debugger)
		self.tabs = DebuggerPanelTabs(debugger, panel)
		self.top = panel.show_tabs_top

	def render(self):
		return [
			ui.div(height=css.header_height)[
				self.debugger_actions,
				ui.span(css=css.phantom_sized_spacer),
				self.tabs
			],
			ui.div(height=0.25, width=self.layout.width() - 5, css=css.seperator) if self.top else None,
			ui.div(height=1, width=1, css=css.seperator_cutout) if self.top else None,
		]

class DebuggerOutputPanel:
	on_opened: Callable[[], Any] | None = None
	on_opened_status: Callable[[], Any] | None = None

	on_closed: Callable[[], Any] | None = None
	
	panels: ClassVar[Dict[int, DebuggerOutputPanel]] = {}

	def __init__(self, debugger: Debugger, panel_name: str, name: str|None = None, show_panel = True, show_tabs = True, show_tabs_top = False, remove_last_newline = False, create = True):
		super().__init__()
		self.panel_name = self._get_free_output_panel_name(debugger.window, panel_name) if create else panel_name
		self.output_panel_name = f'output.{self.panel_name}'
		self.name = name or panel_name

		self.window = debugger.window
		self.create = create
		self.show_tabs = show_tabs
		self.show_tabs_top = show_tabs_top
		self.remove_last_newline = remove_last_newline
		self.debugger = debugger

		# if a panel with the same name already exists add a unique id
		self._locked_selection = 0
		self.status: ui.Image|None = None

		self.removed_newline: int|None = None

		previous_panel = self.window.active_panel()
		self.view = self.window.find_output_panel(self.panel_name) or self.window.create_output_panel(self.panel_name)
		self.controls_and_tabs_phantom = None

		DebuggerOutputPanel.panels[self.view.id()] = self
		self.on_post_show_panel = core.on_post_show_panel.add(self._on_show_panel)
		self.on_pre_hide_panel = core.on_pre_hide_panel.add(self._on_hide_panel)

		settings = self.view.settings()
		if create:
			settings.set('debugger', True)
			settings.set('debugger.output_panel', True)
			settings.set('draw_unicode_white_space', 'none')
			
			settings.set('context_menu', 'DebuggerWidget.sublime-menu')

		settings.set('scroll_past_end', False)
		settings.set('gutter', False)

		if not show_panel and previous_panel:
			self.window.run_command('show_panel', {
				'panel': previous_panel
			})

		if show_tabs and show_tabs_top:
			self.controls_and_tabs = DebuggerConsoleTabs(debugger, self)
			self.controls_and_tabs_phantom = ui.Phantom(self.view, sublime.Region(0, 0), sublime.LAYOUT_INLINE) [
				self.controls_and_tabs
			]
			self.text_change_listner = OutputPanelTopTextChangeListener(self.view)

		elif show_tabs:
			self.controls_and_tabs = DebuggerConsoleTabs(debugger, self)
			self.controls_and_tabs_phantom = ui.Phantom(self.view, sublime.Region(-1), sublime.LAYOUT_BLOCK) [
				self.controls_and_tabs
			]

			self.text_change_listner = OutputPanelBottomTextChangeListener(self)
		else:
			self.text_change_listner = None
			self.controls_and_tabs = None
			self.controls_and_tabs_phantom = None

		debugger.add_output_panel(self)
		self.update_settings()

		self.open()

		# settings = self.view.settings()
		# # this tricks the panel into having a larger height
		# previous_line_padding_top = settings.get('line_padding_top')
		# settings.set('line_padding_top', 250)
		# self.open()
		# settings.set('line_padding_top', previous_line_padding_top)

	def update_settings(self):
		# these settings control the size of the ui calculated in ui/layout
		settings = self.view.settings()
		if Settings.ui_scale:
			settings['font_size'] = Settings.ui_scale
		else:
			settings.erase('font_size')

		settings['rem_width_scale'] = Settings.ui_rem_width_scale

	def set_status(self, status: ui.Image):
		self.status = status
		
		# if the status of a panel changes we need to re-render all the output panels
		for panel in self.debugger.output_panels:
			panel.updated_status()

	def updated_status(self):
		if controls_and_tabs := self.controls_and_tabs:
			controls_and_tabs.dirty()		

	def dispose(self):
		self.debugger.remove_output_panel(self)

		if self.text_change_listner:
			self.text_change_listner.dispose()

		if self.create:
			self.window.destroy_output_panel(self.panel_name)

		self.on_post_show_panel.dispose()
		self.on_pre_hide_panel.dispose()
		if self.controls_and_tabs_phantom:
			self.controls_and_tabs_phantom.dispose()
		del DebuggerOutputPanel.panels[self.view.id()]

	def _get_free_output_panel_name(self, window: sublime.Window, name: str) -> str:
		id = 1
		while True:
			if not f'output.{name}' in window.panels():
				return name

			name = f'{name}({id})'
			id += 1

	def open(self):
		self.window.run_command('show_panel', {
			'panel': self.output_panel_name
		})
		sublime.set_timeout(self.scroll_to_end, 5)

	def open_status(self):
		if on_opened_status := self.on_opened_status:
			on_opened_status()
		else:
			self.open()

	def is_open(self) -> bool:
		return self.window.active_panel() == self.output_panel_name

	def _on_show_panel(self, window: sublime.Window):
		if window == self.window and window.active_panel() == self.output_panel_name:
			self.scroll_to_end()
			if self.on_opened: self.on_opened()

	def _on_hide_panel(self, window: sublime.Window, name: str):
		if self.on_closed and window == self.window and name == self.output_panel_name:
			# run on_closed after hiding the panel otherwise showing other panels will not work
			sublime.set_timeout(self.on_closed, 0)

	def is_locked_selection(self): 
		return self._locked_selection != 0

	def scroll_to_end(self):
		self.lock_selection_temporarily()
		if self.show_tabs_top:
			self.view.set_viewport_position((0, 0), False)
		else:
			height = self.view.layout_extent()[1]
			self.view.set_viewport_position((0, height), False)

	def lock_selection(self):
		self._locked_selection += 1

	def unlock_selection(self):
		self._locked_selection -= 1

	def lock_selection_temporarily(self):
		self.lock_selection()
		sublime.set_timeout(self.unlock_selection, 100)

	def at(self):
		return self.view.size()

	def ensure_new_line(self, text: str, at: int|None = None):
		if at is None:
			at = self.at()

		if self.removed_newline == at:
			return text

		if at != 0 and self.view.substr(at -1) != '\n':
			text = '\n' + text

		return text		


	def on_selection_modified(self): ...
	def on_activated(self): ...
	def on_deactivated(self): ...
	def on_text_command(self, command_name: str, args: Any): ...
	def on_query_context(self, key: str, operator: str, operand: str, match_all: bool) -> bool: ...
	def on_query_completions(self, prefix: str, locations: list[int]) -> Any: ...


class DebuggerConsoleListener (sublime_plugin.EventListener):
	def __init__(self) -> None:
		super().__init__()
		self.phantoms = {}

	def on_selection_modified(self, view: sublime.View) -> None:
		panel = DebuggerOutputPanel.panels.get(view.id())
		if not panel: return

		# the view is locked so we do not allow changing the selection. 
		# This allows the view to be scrolled to the bottom without issues when the selection is changed.
		if panel.is_locked_selection():
			view.sel().clear()

		panel.on_selection_modified()

	def on_activated(self, view: sublime.View):
		if panel := DebuggerOutputPanel.panels.get(view.id()):
			panel.on_activated()

	def on_deactivated(self, view: sublime.View):
		if panel := DebuggerOutputPanel.panels.get(view.id()):
			panel.on_deactivated()

	def on_text_command(self, view: sublime.View, command_name: str, args: Any):
		if panel := DebuggerOutputPanel.panels.get(view.id()):
			return panel.on_text_command(command_name, args)

	def on_query_context(self, view: sublime.View, key: str, operator: str, operand: str, match_all: bool) -> bool:
		if key != 'debugger':
			return False

		if panel := DebuggerOutputPanel.panels.get(view.id()):
			return panel.on_query_context(key, operator, operand, match_all)

		return False

	def on_query_completions(self, view: sublime.View, prefix: str, locations: list[int]) -> Any:
		if panel := DebuggerOutputPanel.panels.get(view.id()):
			return panel.on_query_completions(prefix, locations)

class OutputPanelTopTextChangeListener(sublime_plugin.TextChangeListener):
	def __init__(self, view: sublime.View) -> None:
		super().__init__()
		self.view = view
		self.inside_on_text_changed = False

		self.attach(view.buffer())
		self.on_text_changed(None)

	def dispose(self):
		if self.is_attached():
			self.detach()

	def on_text_changed(self, changes: Any):
		if self.inside_on_text_changed:
			return

		self.inside_on_text_changed  = True
		core.edit(self.view, self._on_text_changed)
		self.inside_on_text_changed  = False

	def _on_text_changed(self, edit: sublime.Edit):
		is_readonly = self.view.is_read_only()
		self.view.set_read_only(False)

		if self.view.substr(0) != '\n':			
			self.view.insert(edit, 0, '\n')

		self.view.set_read_only(is_readonly)

class OutputPanelBottomTextChangeListener(sublime_plugin.TextChangeListener):
	def __init__(self, panel: DebuggerOutputPanel) -> None:
		super().__init__()
		self.panel = panel
		self.view = panel.view
		self.inside_on_text_changed = False

		self.attach(self.view.buffer())
		self.on_text_changed(None)

	def dispose(self):
		if self.is_attached():
			self.detach()

	def on_text_changed(self, changes: None):
		if self.inside_on_text_changed:
			return

		self.inside_on_text_changed  = True
		core.edit(self.view, self._on_text_changed)
		self.inside_on_text_changed  = False


	def _on_text_changed(self, edit: sublime.Edit):
		is_readonly = self.view.is_read_only()
		self.view.set_read_only(False)

		# ensure panel is at least 25 lines since we need the height of the content to be more than its viewport height
		line_count = self.view.rowcol(self.view.size())[0] + 1
		if line_count < 25:
			self.view.insert(edit, 0, 25 * '\n')

		# re-insert the newline we removed
		if self.panel.removed_newline:
			removed_newline = self.view.transform_region_from(sublime.Region(self.panel.removed_newline), self.removed_newline_change_id)
			self.panel.removed_newline = None
			self.view.insert(edit, removed_newline.a, '\n')

		at = self.panel.at() - 1
		last = self.view.substr(at)

		# remove newline
		if self.panel.remove_last_newline and last == '\n':
			self.view.erase(edit, sublime.Region(at, at+1))
			self.panel.removed_newline = at
			self.removed_newline_change_id = self.view.change_id()

		if self.panel.controls_and_tabs_phantom:
			self.panel.controls_and_tabs_phantom.dirty()

		self.view.set_read_only(is_readonly)
