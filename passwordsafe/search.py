# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import threading
import typing
from typing import Optional

from gi.repository import Gio, GLib, GObject, Gtk, Handy

import passwordsafe.config_manager as config
from passwordsafe.safe_element import SafeElement, SafeEntry, SafeGroup
from passwordsafe.sorting import SortingHat

if typing.TYPE_CHECKING:
    from passwordsafe.database_manager import DatabaseManager
    from passwordsafe.unlocked_database import UnlockedDatabase


class Search:
    # pylint: disable=too-many-instance-attributes

    _result_list = Gio.ListStore.new(SafeElement)
    search_list_box = NotImplemented

    def __init__(self, unlocked_database: UnlockedDatabase) -> None:
        self.unlocked_database: UnlockedDatabase = unlocked_database
        self._db_manager: DatabaseManager = unlocked_database.database_manager
        self._search_changed_id: Optional[int] = None

        self._builder: Gtk.Builder = Gtk.Builder()
        self._builder.add_from_resource("/org/gnome/PasswordSafe/search.ui")

        self._stack: Gtk.Stack = self._builder.get_object("stack")
        self._empty_search_page: Gtk.Box = self._builder.get_object(
            "empty_search_page")
        self._info_search_page: Gtk.Box = self._builder.get_object(
            "info_search_page")
        self._results_search_page: Gtk.Box = self._builder.get_object(
            "results_search_page")

        self.scrolled_page = self._builder.get_object(
            "stack")

        self._search_entry = self._builder.get_object("headerbar_search_entry")
        self._headerbar: Handy.HeaderBar = self._builder.get_object(
            "headerbar_search")

        self._key_pressed: bool = False
        self._timeout_search: int = 0

        self._timeout_info: int = 0
        self._search_text: str = self._search_entry.props.text
        self._result_list.connect("items_changed", self._on_items_changed)

    def _on_items_changed(
        self, list_model: Gio.ListModel, _pos: int, _removed: int, _added: int
    ) -> None:
        if list_model.get_n_items() == 0:
            if len(self._search_text) < 2:
                self._display_info_page()

    def initialize(self):
        # Search Headerbar
        self._search_entry.connect("activate", self.on_headerbar_search_entry_enter_pressed)

        self.unlocked_database.bind_accelerator(
            self._search_entry, "<primary>f", signal="stop-search")
        self.unlocked_database.connect(
            "notify::search-active", self._on_search_active)
        self._prepare_search_page()

    # Search headerbar
    def _on_search_active(
        self, _db_view: UnlockedDatabase, _value: GObject.ParamSpecBoolean
    ) -> None:
        """Update the view when the search view is activated or
        deactivated.

        :param UnlockedDatabase db_view: unlocked_database view
        :param GObject.ParamSpecBoolean value: new value as GParamSpec
        """
        search_active = self.unlocked_database.props.search_active

        if search_active:
            self._search_changed_id = self._search_entry.connect(
                "search-changed", self._on_search_entry_timeout)
            self._search_entry.grab_focus()

            self._timeout_info = GLib.timeout_add(200, self._display_info_page)

        else:
            if self._search_changed_id is not None:
                self._search_entry.disconnect(self._search_changed_id)
                self._search_changed_id = None

            self._search_entry.props.text = ""
            self._key_pressed = False
            self._result_list.remove_all()

    def _prepare_search_page(self):
        self.search_list_box = self._builder.get_object("list_box")
        self.search_list_box.bind_model(
            self._result_list, self.unlocked_database.listbox_row_factory
        )
        self.search_list_box.connect(
            "row-activated", self.unlocked_database.on_list_box_row_activated
        )

    def _display_info_page(self) -> bool:
        """When search-mode is activated the search text has not been
        entered yet. The info_search overlay only needs to be displayed
        if the search text is empty."""
        if self._timeout_info > 0:
            GLib.source_remove(self._timeout_info)
            self._timeout_info = 0

        if not self._key_pressed:
            self._stack.set_visible_child(self._info_search_page)

        return GLib.SOURCE_REMOVE

    def _start_search(self):
        """Update the overlays and start a search
        if the search term is not empty.
        """
        if self._search_text:
            search_thread = threading.Thread(target=self._perform_search)
            search_thread.daemon = True
            search_thread.start()
        else:
            self._stack.set_visible_child(self._info_search_page)

    def _perform_search(self):
        """Search for results in the database."""
        querry = self._search_text

        db_manager = self.unlocked_database.database_manager

        def filter_func(element: SafeElement) -> bool:
            if element.is_group:
                fields = [element.name, element.notes]
            else:
                fields = [element.name, element.notes, element.url, element.username]

            for field in fields:
                if querry.lower() in field.lower():
                    return True

            return False

        db_entries = filter(
            filter_func, [SafeEntry(db_manager, e) for e in db_manager.db.entries]
        )
        db_groups = filter(
            filter_func,
            [
                SafeGroup(db_manager, g)
                for g in db_manager.db.groups
                if not g.is_root_group
            ],
        )
        results = list(db_groups) + list(db_entries)

        if len(results) == 0:
            self._stack.set_visible_child(self._empty_search_page)
            return

        GLib.idle_add(self._show_results, results)

    def _show_results(self, results):
        n_items = self._result_list.get_n_items()
        self._result_list.splice(0, n_items, results)

        # Sort the results
        sorting = config.get_sort_order()
        sort_func = SortingHat.get_sort_func(sorting)
        self._result_list.sort(sort_func)

        self._stack.set_visible_child(self._results_search_page)

        return GLib.SOURCE_REMOVE

    # Events

    def _on_search_entry_timeout(self, widget: Gtk.Entry) -> None:
        self._key_pressed = True
        if self._timeout_search > 0:
            GLib.source_remove(self._timeout_search)

        # Time between search querries.
        self._timeout_search = GLib.timeout_add(
            200, self._on_search_entry_changed, widget
        )

    def _on_search_entry_changed(self, widget):
        self.unlocked_database.start_database_lock_timer()

        self._timeout_search = 0

        self._search_text = widget.get_text()
        self._start_search()

        return False

    def on_headerbar_search_entry_enter_pressed(self, _widget):
        self.unlocked_database.start_database_lock_timer()

        # Do nothing on empty search terms or no search results
        if not self._search_text:
            return
        if not self.search_list_box.get_children():
            return

        selected_row = self.search_list_box.get_selected_row()

        if selected_row is None:
            selected_row = self.search_list_box.get_children()[0]

        selected_row.activate()

    @property
    def headerbar(self) -> Handy.HeaderBar:
        """Get the search headerbar.

        :returns: the search headerbar
        :rtype: Handy.Headerbar
        """
        return self._headerbar
