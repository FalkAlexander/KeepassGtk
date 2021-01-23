# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import logging
import threading
import typing
from gettext import gettext as _
from typing import Any, List, Optional

from gi.repository import Gdk, Gio, GLib, GObject, Gtk

import passwordsafe.config_manager
from passwordsafe.custom_keypress_handler import CustomKeypressHandler
from passwordsafe.database_settings_dialog import DatabaseSettingsDialog
from passwordsafe.entry_page import EntryPage
from passwordsafe.entry_row import EntryRow
from passwordsafe.group_page import GroupPage
from passwordsafe.group_row import GroupRow
from passwordsafe.pathbar import Pathbar
from passwordsafe.properties_dialog import PropertiesDialog
from passwordsafe.references_dialog import ReferencesDialog
from passwordsafe.safe_element import SafeElement, SafeEntry, SafeGroup
from passwordsafe.search import Search
from passwordsafe.sorting import SortingHat
from passwordsafe.unlocked_headerbar import UnlockedHeaderBar

if typing.TYPE_CHECKING:
    from uuid import UUID

    from passwordsafe.container_page import ContainerPage
    from passwordsafe.database_manager import DatabaseManager
    from passwordsafe.selection_ui import SelectionUI
    # pylint: disable=ungrouped-imports
    from passwordsafe.main_window import MainWindow


class UnlockedDatabase(GObject.GObject):
    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-many-public-methods

    # Widgets
    headerbar = NotImplemented
    scrolled_window = NotImplemented
    divider = NotImplemented
    revealer = NotImplemented
    action_bar = NotImplemented
    pathbar = NotImplemented

    # Objects
    builder = NotImplemented
    scheduled_tmpfiles_deletion: List[Gio.File] = []
    clipboard = NotImplemented
    clipboard_timer_handler: Optional[int] = None
    _current_element: Optional[SafeElement] = None
    _lock_timer_handler: Optional[int] = None
    save_loop: Optional[int] = None  # If int, a thread periodically saves the database
    dbus_subscription_id = NotImplemented

    selection_mode = GObject.Property(
        type=bool, default=False, flags=GObject.ParamFlags.READWRITE
    )

    def __init__(self, window: MainWindow, widget: ContainerPage, dbm: DatabaseManager):
        super().__init__()
        # Instances
        self.builder = Gtk.Builder.new_from_resource(
            "/org/gnome/PasswordSafe/unlocked_database.ui"
        )
        self.window: MainWindow = window
        self.parent_widget: ContainerPage = widget
        self.database_manager: DatabaseManager = dbm
        self.search: Search = Search(self)
        self.custom_keypress_handler: CustomKeypressHandler = CustomKeypressHandler(
            self
        )
        # UnlockedDatabase-specific key accelerators
        self.accelerators: Gtk.AccelGroup = Gtk.AccelGroup()
        self.window.add_accel_group(self.accelerators)

        root_group = SafeGroup.get_root(dbm)
        self.props.current_element = root_group

        # Declare database as opened
        self.window.opened_databases.append(self)

        self._search_active = False

        # Browser Mode
        self.assemble_listbox()
        self.start_save_loop()
        self.custom_keypress_handler.register_custom_events()
        self.register_dbus_signal()

        self.database_manager.connect("notify::locked", self._on_database_lock_changed)
        self.database_manager.connect("save-notification", self.on_database_save_notification)

    def listbox_row_factory(self, element: SafeElement) -> Gtk.Widget:
        if element.is_entry:
            return EntryRow(self, element)

        return GroupRow(self, element)

    def populate_list_model(self, list_model: Gio.ListStore) -> None:
        entries = self.props.current_element.entries
        groups = [g for g in self.props.current_element.subgroups if not g.is_root_group]

        elements = groups + entries
        list_model.splice(0, 0, elements)
        for elem in list_model:
            elem.sorted_handler_id = elem.connect(
                "notify::name", self._on_element_renamed, list_model
            )

        self.sort_list_model(self, list_model)

    def sort_list_model(
            self, _unlocked_db: UnlockedDatabase, list_model: Gio.ListStore, _data: Any = None
    ) -> None:
        sorting = passwordsafe.config_manager.get_sort_order()
        sort_func = SortingHat.get_sort_func(sorting)

        list_model.sort(sort_func)

    #
    # Stack Pages
    #

    def assemble_listbox(self):
        self._edit_page_box = self.builder.get_object("_edit_page_box")
        self.pathbar = Pathbar(self, self.database_manager)
        self._stack = self.builder.get_object("list_stack")
        self._unlocked_db_stack = self.builder.get_object("_unlocked_db_stack")
        self.revealer = self.builder.get_object("revealer")
        self.action_bar = self.builder.get_object("action_bar")
        self._unlocked_db_deck = self.builder.get_object("_unlocked_db_deck")

        self.headerbar = UnlockedHeaderBar(self)
        self.selection_ui = self.headerbar.selection_ui

        self.selection_ui.connect("notify::selected-elements", self.headerbar._on_selected_entries_changed)

        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        # Contains the "main page" with the BrowserListBox.
        self.divider = self.builder.get_object("divider")
        self._unlocked_db_stack.add_named(self.search.scrolled_page, "search")
        self.search.scrolled_page.show_all()
        self.parent_widget.add(self.divider)

        self.search.initialize()
        self._update_headerbar()

        self.start_database_lock_timer()

        self.show_browser_page(self.current_element)

    def show_edit_page(self, element: SafeElement, new: bool = False) -> None:
        self.start_database_lock_timer()
        self.props.current_element = element

        # Sets the accessed time.
        self.database_manager.set_element_atime(element.element)

        if element.is_group:
            page = GroupPage(self)
            self.headerbar.mode = UnlockedHeaderBar.Mode.GROUP_EDIT
        else:
            page = EntryPage(self, new)
            self.headerbar.mode = UnlockedHeaderBar.Mode.ENTRY

        page_box = self._edit_page_box

        # TODO Use the set_child api in GTK 4 with a StackPage.
        while page_box.get_children():
            page_box.remove(page_box.get_children()[0])

        page_box.add(page)
        self._unlocked_db_deck.set_visible_child(self._edit_page_box)

    def show_browser_page(self, group: SafeGroup) -> None:
        self.start_database_lock_timer()
        self.props.current_element = group

        self._unlocked_db_stack.set_visible_child(self._stack)
        self._unlocked_db_deck.set_visible_child(self._unlocked_db_stack)
        self.headerbar.mode = UnlockedHeaderBar.Mode.GROUP

        page_name = self.props.current_element.uuid.urn

        if not self._stack.get_child_by_name(page_name):
            new_page = self.new_group_browser_page(group)
            self._stack.add_named(new_page, page_name)

        self._stack.set_visible_child_name(page_name)

    def _on_element_renamed(
        self,
        element: SafeElement,
        _value: GObject.ParamSpec,
        list_model: Gio.ListStore,
    ) -> None:
        pos = 0
        found = False
        # Disconnect previous signal
        if element.sorted_handler_id:
            element.disconnect(element.sorted_handler_id)
            element.sorted_handler_id = None

        # We check if element is in the list model
        for elem in list_model:
            if elem.uuid == element.uuid:
                found = True
                break
            pos += 1

        if found:
            sorting = passwordsafe.config_manager.get_sort_order()
            sort_func = SortingHat.get_sort_func(sorting)

            list_model.remove(pos)
            list_model.insert_sorted(element, sort_func)
            element.sorted_handler_id = element.connect(
                "notify::name", self._on_element_renamed, list_model
            )
        else:
            logging.debug("No.")

    def _on_element_added(
            self,
            _u_db: UnlockedDatabase,
            element: SafeElement,
            target_group_uuid: UUID,
            list_model: Gio.ListStore,
            list_model_group_uuid: UUID,
            _data: Any = None
    ) -> None:
        # Return if the element was addded to another group than the one
        # used to generate the list model.
        if target_group_uuid != list_model_group_uuid:
            return

        sorting = passwordsafe.config_manager.get_sort_order()
        sort_func = SortingHat.get_sort_func(sorting)
        list_model.insert_sorted(element, sort_func)
        element.sorted_handler_id = element.connect(
            "notify::name", self._on_element_renamed, list_model
        )

    def _on_element_removed(
            self, _u_db: UnlockedDatabase, element_uuid: UUID, list_model: Gio.ListStore, _data: Any = None
    ) -> None:
        pos = 0
        found = False
        for element in list_model:
            if element.uuid == element_uuid:
                found = True
                break
            pos += 1

        # Only removes the element if it is the current list model
        if found:
            list_model.remove(pos)

    def _on_element_moved(
        self,
        _u_db: UnlockedDatabase,
        moved_element: SafeElement,
        old_loc_uuid: UUID,
        new_loc_uuid: UUID,
        list_model: Gio.ListStore,
        list_model_group_uuid: UUID,
    ) -> None:
        # pylint: disable=too-many-arguments
        """Moves the element to a new list model.
        If the listmodel corresponds to the old group we remove it,
        and if corresponds to the new location, we add it."""
        if list_model_group_uuid == old_loc_uuid:
            pos = 0
            found = False
            for element in list_model:
                if element.uuid == moved_element.uuid:
                    found = True
                    break
                pos += 1

            if found:
                list_model.remove(pos)

        if list_model_group_uuid == new_loc_uuid:
            sorting = passwordsafe.config_manager.get_sort_order()
            sort_func = SortingHat.get_sort_func(sorting)
            list_model.insert_sorted(moved_element, sort_func)
            moved_element.sorted_handler_id = moved_element.connect(
                "notify::name", self._on_element_renamed, list_model
            )

    def new_group_browser_page(self, group: SafeGroup) -> Gtk.ScrolledWindow:
        builder = Gtk.Builder()
        builder.add_from_resource(
            "/org/gnome/PasswordSafe/unlocked_database.ui"
        )
        browser_clamp = builder.get_object("browser_clamp")
        browser_stack = builder.get_object("browser_stack")
        empty_group_box = builder.get_object("empty_group_box")

        list_box = builder.get_object("list_box")
        list_box.connect("row-activated", self.on_list_box_row_activated)
        list_model = Gio.ListStore.new(SafeElement)

        settings = self.window.application.settings
        settings.connect("changed", self.on_sort_order_changed, list_model)
        self.database_manager.connect(
            "element-removed", self._on_element_removed, list_model
        )
        self.database_manager.connect(
            "element-added", self._on_element_added, list_model, group.uuid
        )
        self.database_manager.connect(
            "element-moved", self._on_element_moved, list_model, group.uuid
        )
        self.selection_ui.connect("clear-selection", self._on_clear_selection, list_box)

        list_box.bind_model(list_model, self.listbox_row_factory)
        list_model.connect(
            "items-changed",
            self.on_listbox_items_changed,
            browser_stack,
            browser_clamp,
            empty_group_box)
        self.populate_list_model(list_model)

        scrolled_window = Gtk.ScrolledWindow.new()
        scrolled_window.props.visible = True
        scrolled_window.add(browser_stack)

        return scrolled_window

    @property
    def in_edit_page(self) -> bool:
        """Returns true if the current visible page is either
        the Group edit page or Entry edit page."""

        boolean: bool = self._unlocked_db_deck.props.visible_child == self._edit_page_box
        return boolean

    #
    # Headerbar
    #

    def _update_headerbar(self) -> None:
        """Display the correct headerbar according to search state."""
        if self.props.search_active:
            self.parent_widget.set_headerbar(self.search.headerbar)
            self.window.set_titlebar(self.search.headerbar)
        else:
            self.parent_widget.set_headerbar(self.headerbar)
            self.window.set_titlebar(self.headerbar)

    #
    # Keystrokes
    #

    def bind_accelerator(self, widget, accelerator, signal="clicked"):
        """bind accelerators to self, aka this `UnlockedDatabase`"""
        key, mod = Gtk.accelerator_parse(accelerator)
        widget.add_accelerator(
            signal, self.accelerators, key, mod, Gtk.AccelFlags.VISIBLE
        )

    #
    # Group and Entry Management
    #

    def on_listbox_items_changed(self, listmodel, _position, _removed, _added, browser_stack, browser_clamp, empty_group_box):
        if not listmodel.get_n_items():
            browser_stack.set_visible_child(empty_group_box)
        else:
            browser_stack.set_visible_child(browser_clamp)

    @GObject.Property(type=SafeElement, flags=GObject.ParamFlags.READWRITE)
    def current_element(self) -> SafeElement:
        return self._current_element

    @current_element.setter  # type: ignore
    def current_element(self, element: SafeElement) -> None:
        self._current_element = element

    def get_current_page(self) -> Gtk.ScrolledWindow:
        """Returns the page associated with current_element.

        :returns: current page
        :rtype: Gtk.Widget
        """
        element_uuid = self.props.current_element.uuid
        return self._stack.get_child_by_name(element_uuid.urn)

    #
    # Events
    #

    def on_list_box_row_activated(self, _widget, list_box_row):
        self.start_database_lock_timer()

        if self.props.search_active:
            self.props.search_active = False

        if list_box_row.type == "GroupRow":
            safe_group = list_box_row.safe_group
            self.show_browser_page(safe_group)
        else:
            if self.selection_mode:
                active = list_box_row.selection_checkbox.props.active
                list_box_row.selection_checkbox.props.active = not active
                return

            safe_entry = list_box_row.safe_entry
            self.show_edit_page(safe_entry)

    def on_database_save_notification(self, _database_manager: DatabaseManager, saved: bool) -> None:
        if saved:
            self.window.notify(_("Safe saved"))
        else:
            self.window.notify(_("Could not save Safe"))

    def save_safe(self):
        if self.database_manager.is_dirty is True:
            if self.database_manager.save_running is False:
                self.save_database(notification=True)
            else:
                # NOTE: In-app notification to inform the user that already an unfinished save job is running
                self.window.notify(
                    _("Please wait. Another save is running.")
                )
        else:
            # NOTE: In-app notification to inform the user that no save is necessary because there where no changes made
            self.window.notify(_("No changes made"))

    def lock_safe(self):
        self.database_manager.props.locked = True

    def on_add_entry_action(self, _action: Gio.SimpleAction) -> None:
        """CB when the Add Entry menu was clicked"""
        group = self.props.current_element.group
        new_entry: SafeEntry = self.database_manager.add_entry_to_database(group)
        self.show_edit_page(new_entry, new=True)

    def on_add_group_action(self, _action: Gio.SimpleAction) -> None:
        """CB when menu entry Add Group is clicked"""
        self.database_manager.is_dirty = True
        safe_group = self.database_manager.add_group_to_database(
            "", "0", "", self.props.current_element.group
        )
        self.show_edit_page(safe_group)

    def on_element_delete_menu_button_clicked(
        self, _action: Gio.SimpleAction, _param: None
    ) -> None:
        """Delete the visible entry from the menu."""
        parent_group = self.props.current_element.parentgroup
        self.database_manager.delete_from_database(self.props.current_element.element)

        self.show_browser_page(parent_group)

    def on_entry_duplicate_menu_button_clicked(self, _action, _param):
        self.database_manager.duplicate_entry(self.props.current_element.entry)
        parent_group = self.props.current_element.parentgroup

        self.show_browser_page(parent_group)

    def send_to_clipboard(self, text: str, message: str = "") -> None:
        if not message:
            message = _("Copied to clipboard")

        self.start_database_lock_timer()

        if self.clipboard_timer_handler:
            GLib.source_remove(self.clipboard_timer_handler)
            self.clipboard_timer_handler = None

        self.clipboard.set_text(text, -1)

        self.window.notify(message)

        clear_clipboard_time = passwordsafe.config_manager.get_clear_clipboard()
        self.clipboard_timer_handler = GLib.timeout_add_seconds(
            clear_clipboard_time, self.clipboard.clear
        )

    def on_database_settings_entry_clicked(self, _action, _param):
        DatabaseSettingsDialog(self).present()

    def on_session_lock(
        self, _connection, _unique_name, _object_path, _interface, _signal, state
    ):
        if state[0] and not self.database_manager.props.locked:
            self.lock_timeout_database()

    def on_sort_order_changed(self, settings, key, list_model):
        """Callback to be executed when the sorting has been changed."""
        if key == "sort-order":
            sorting = settings.get_enum("sort-order")
            logging.debug("Sort order changed to %s", sorting)

            self.sort_list_model(self, list_model)
    #
    # Dialog Creator
    #

    def show_references_dialog(self, _action: Gio.SimpleAction, _param: None) -> None:
        """Show a Group/Entry reference dialog

        Invoked by the app.entry.references action"""
        ReferencesDialog(self).present()

    def show_properties_dialog(self, _action: Gio.SimpleAction, _param: None) -> None:
        """Show a Group/Entry property dialog

        Invoked by the app.element.properties action"""
        PropertiesDialog(self).present()

    #
    # Utils
    #

    def _on_database_lock_changed(self, _database_manager, _value):
        locked = self.database_manager.props.locked
        if locked:
            self.cleanup(False)

            for tmpfile in self.scheduled_tmpfiles_deletion:
                try:
                    tmpfile.delete()
                except GLib.Error as exc:  # pylint: disable=broad-except
                    logging.warning(
                        "Skipping deletion of tmpfile %s: %s",
                        tmpfile.get_path(),
                        exc.message,
                    )

            if passwordsafe.config_manager.get_save_automatically():
                self.save_database()

            self.divider.hide()
        else:
            self._update_headerbar()
            self.start_save_loop()
            self.divider.show()
            self.start_database_lock_timer()

    def lock_timeout_database(self):
        self.database_manager.props.locked = True

        # NOTE: Notification that a safe has been locked.
        self.window.notify(_("Safe locked due to inactivity"))

    #
    # Helper Methods
    #

    def cleanup(self, delete_tmp_file: bool = True) -> None:
        """Stop all ongoing operations:

        * stop the save loop
        * cancel all timers
        * unregistrer from dbus
        * delete all temporary file is delete_tmp_file is True

        :param bool show_save_dialog: chooe to delete temporary files
        """
        logging.debug("Cleaning database %s", self.database_manager.database_path)

        if self.clipboard_timer_handler:
            GLib.source_remove(self.clipboard_timer_handler)
            self.clipboard_timer_handler = None
            self.clipboard.clear()

        if self._lock_timer_handler:
            GLib.source_remove(self._lock_timer_handler)
            self._lock_timer_handler = None

        # Do not listen to screensaver kicking in anymore
        connection = Gio.Application.get_default().get_dbus_connection()
        connection.signal_unsubscribe(self.dbus_subscription_id)

        # stop the save loop
        if self.save_loop:
            GLib.source_remove(self.save_loop)
            self.save_loop = None

        if not delete_tmp_file:
            return

        for tmpfile in self.scheduled_tmpfiles_deletion:
            try:
                tmpfile.delete()
            except Gio.Error:
                logging.warning("Skipping deletion of tmpfile...")

    def save_database(self, notification: bool = False) -> None:
        """Save the database.

        If auto_save is False, a dialog asking for confirmation
        will be displayed.
        """
        if not self.database_manager.is_dirty or self.database_manager.save_running:
            return

        save_thread = threading.Thread(target=self.database_manager.save_database, args=[notification])
        save_thread.daemon = False
        save_thread.start()

        logging.debug("Saving database %s", self.database_manager.database_path)

    def start_database_lock_timer(self):
        if self._lock_timer_handler:
            GLib.source_remove(self._lock_timer_handler)
            self._lock_timer_handler = None

        if self.database_manager.props.locked:
            return

        timeout = passwordsafe.config_manager.get_database_lock_timeout() * 60
        if timeout:
            self._lock_timer_handler = GLib.timeout_add_seconds(
                timeout, self.lock_timeout_database
            )

    def start_save_loop(self):
        self.save_loop = GLib.timeout_add_seconds(30, self.threaded_save_loop)

    def threaded_save_loop(self) -> bool:
        """Saves the safe as long as it returns True."""
        if passwordsafe.config_manager.get_save_automatically() is True:
            self.database_manager.save_database()

        return True

    #
    # DBus
    #

    def register_dbus_signal(self) -> None:
        """Register a listener so we get notified about screensave kicking in

        In this case we will call self.on_session_lock()"""
        connection = Gio.Application.get_default().get_dbus_connection()
        self.dbus_subscription_id = connection.signal_subscribe(
            None, "org.gnome.ScreenSaver", "ActiveChanged",
            "/org/gnome/ScreenSaver", None,
            Gio.DBusSignalFlags.NONE, self.on_session_lock,)

    def go_back(self):
        if self.props.selection_mode:
            self.props.selection_mode = False
            return
        if self.props.search_active:
            self.props.search_active = False
            return
        if self.props.current_element.is_root_group:
            return

        parent = self.props.current_element.parentgroup
        self.show_browser_page(parent)

    @GObject.Property(type=bool, default=False, flags=GObject.ParamFlags.READWRITE)
    def search_active(self) -> bool:
        """Property to know if search is active.

        It is used by Search to update the widgets (mainly the
        headerbar) accordingly.

        :returns: True is search is active
        :rtype: bool
        """
        return self._search_active

    @search_active.setter  # type: ignore
    def search_active(self, value: bool) -> None:
        """Set the search mode

        :param value: new search_active
        """
        self._search_active = value
        if self._search_active:
            self._unlocked_db_stack.set_visible_child_name("search")
        else:
            self.show_browser_page(self.current_element)

        self._update_headerbar()

    @GObject.Property(type=bool, default=False, flags=GObject.ParamFlags.READWRITE)
    def database_locked(self):
        """Get database lock status

        :returns: True if the database is locked
        :rtype: bool
        """
        return self.database_manager.props.locked

    def _on_clear_selection(self, _selection_ui: SelectionUI, list_box: Gtk.ListBox) -> None:
        for row in list_box:
            row.selection_checkbox.props.active = False
