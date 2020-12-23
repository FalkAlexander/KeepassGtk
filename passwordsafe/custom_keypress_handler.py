# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import typing

from gi.repository import Gdk, Gtk

import passwordsafe.pathbar_button
from passwordsafe.entry_row import EntryRow
from passwordsafe.group_row import GroupRow

if typing.TYPE_CHECKING:
    from passwordsafe.main_window import MainWindow


class CustomKeypressHandler:
    #
    # Global Variables
    #

    unlocked_database = NotImplemented

    #
    # Init
    #

    def __init__(self, u_d):
        self.unlocked_database = u_d

    #
    # Special Keys (e.g. type-to-search)
    #

    def register_custom_events(self):
        self.unlocked_database.window.connect("key-press-event", self.on_special_key_pressed)
        self.unlocked_database.window.connect("button-release-event", self._on_button_released)

    def on_special_key_pressed(self, window: MainWindow, eventkey: Gtk.Event) -> bool:
        # pylint: disable=too-many-return-statements
        # pylint: disable=too-many-branches
        if not self._current_view_accessible():
            return Gdk.EVENT_PROPAGATE

        scrolled_page = self.unlocked_database.get_current_page()
        if (scrolled_page.edit_page
                and eventkey.keyval == Gdk.KEY_Tab):
            focused_entry = self.unlocked_database.window.get_focus()
            if focused_entry and "TabBox" in focused_entry.get_name():
                self.tab_to_next_input_entry(scrolled_page)
                return Gdk.EVENT_PROPAGATE

        # Handle undo and redo on entries.
        elif (
            scrolled_page.edit_page
            and eventkey.state & Gdk.ModifierType.CONTROL_MASK
            == Gdk.ModifierType.CONTROL_MASK
        ):
            keyval_name = Gdk.keyval_name(eventkey.keyval)
            if isinstance(window.get_focus(), Gtk.TextView):
                textbuffer = window.get_focus().get_buffer()
                if isinstance(textbuffer, passwordsafe.history_buffer.HistoryTextBuffer):
                    if keyval_name == 'y':
                        textbuffer.logic.do_redo()
                        return Gdk.EVENT_PROPAGATE
                    if keyval_name == "z":
                        textbuffer.logic.do_undo()
                        return Gdk.EVENT_PROPAGATE
            if isinstance(window.get_focus(), Gtk.Entry):
                textbuffer = window.get_focus().get_buffer()
                if isinstance(textbuffer, passwordsafe.history_buffer.HistoryEntryBuffer):
                    if keyval_name == 'y':
                        textbuffer.logic.do_redo()
                        return Gdk.EVENT_PROPAGATE
                    if keyval_name == "z":
                        textbuffer.logic.do_undo()
                        return Gdk.EVENT_PROPAGATE
        # Handle Return on EntryRow and GroupRow
        elif eventkey.keyval == Gdk.KEY_Return:
            focused_entry = self.unlocked_database.window.get_focus()
            unlocked_db = self.unlocked_database
            if isinstance(focused_entry, EntryRow):
                entry = unlocked_db.database_manager.get_entry_object_from_uuid(
                    focused_entry.get_uuid())
                unlocked_db.show_element(entry)
                return Gdk.EVENT_PROPAGATE
            if isinstance(focused_entry, GroupRow):
                entry = unlocked_db.database_manager.get_group(
                    focused_entry.get_uuid())
                unlocked_db.show_element(entry)
                return Gdk.EVENT_PROPAGATE
        elif (not scrolled_page.edit_page
              and (eventkey.string.isalnum())):
            self.unlocked_database.props.search_active = True

        return Gdk.EVENT_PROPAGATE

    def tab_to_next_input_entry(self, scrolled_page):
        focus_widget = self.unlocked_database.window.get_focus()
        focus_widget_index = focus_widget.get_parent().get_children().index(focus_widget)
        new_index = focus_widget_index + 1
        if new_index < len(focus_widget.get_parent().get_children()):
            if focus_widget.get_parent().get_children()[new_index].get_name() == "TabBox_Next":
                self.unlocked_database.window.set_focus(focus_widget.get_parent().get_children()[new_index])
                return

        rows = scrolled_page.properties_list_box.get_children()
        current_row = self.iterate_parents(self.unlocked_database.window.get_focus())
        current_index = rows.index(current_row)
        new_index = current_index + 1
        if new_index < len(rows):
            next_row = rows[new_index]
        else:
            next_row = rows[0]

        if next_row.get_name() == "ShowAllRow":
            next_row = rows[0]

        self.interate_to_next_input(next_row)

    def interate_to_next_input(self, parent):
        if parent.get_name() == "TabBox":
            self.unlocked_database.window.set_focus(parent)
            return

        if hasattr(parent, "get_children"):
            for child in parent.get_children():
                if child.get_name() == "TabBox":
                    self.unlocked_database.window.set_focus(child)
                else:
                    self.interate_to_next_input(child)

    def iterate_parents(self, child):
        """Return `child` or the first parent of it which is a Gtk.ListBoxRow

        :returns: `child` or the first parent of it which is a Gtk.ListBoxRow
                  or `None` if nothing matches."""
        if isinstance(child, Gtk.ListBoxRow):
            return child
        if hasattr(child, "get_parent"):
            return self.iterate_parents(child.get_parent())
        return None

    def _current_view_accessible(self):
        """Check that the current view is accessible:
         * selection mode is not active
         * search mode is not active
         * current database is not locked
        """
        db_view = self.unlocked_database
        if (not db_view.window.tab_visible(db_view.parent_widget)
                or db_view.props.database_locked
                or db_view.props.selection_mode
                or db_view.search_active):
            return False

        return True

    def _on_button_released(
            self, _window: MainWindow, event: Gtk.Event) -> bool:
        """Go to the parent group with the back button.

        :param Gtk.Widget window: the main window
        :param Gtk.Event event: the event
        """
        # Mouse button 8 is the back button.
        if event.button == 8:
            self.unlocked_database.go_back()
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE
