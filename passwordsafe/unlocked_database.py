# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import logging
import os
import threading
import typing
from enum import IntEnum
from gettext import gettext as _

from gi.repository import Gdk, Gio, GLib, GObject, Gtk

import passwordsafe.config_manager
from passwordsafe import const
from passwordsafe.entry_page import EntryPage
from passwordsafe.entry_row import EntryRow
from passwordsafe.group_page import GroupPage
from passwordsafe.group_row import GroupRow
from passwordsafe.pathbar import Pathbar
from passwordsafe.safe_element import SafeElement, SafeEntry, SafeGroup
from passwordsafe.unlocked_headerbar import UnlockedHeaderBar
from passwordsafe.widgets.database_settings_dialog import DatabaseSettingsDialog
from passwordsafe.widgets.edit_element_headerbar import EditElementHeaderbar, PageType
from passwordsafe.widgets.properties_dialog import PropertiesDialog
from passwordsafe.widgets.references_dialog import ReferencesDialog
from passwordsafe.widgets.search import Search
from passwordsafe.widgets.search_headerbar import SearchHeaderbar
from passwordsafe.widgets.selection_mode_headerbar import SelectionModeHeaderbar
from passwordsafe.widgets.unlocked_database_page import UnlockedDatabasePage

if typing.TYPE_CHECKING:
    from passwordsafe.database_manager import DatabaseManager
    from passwordsafe.widgets.window import Window


@Gtk.Template(resource_path="/org/gnome/PasswordSafe/unlocked_database.ui")
class UnlockedDatabase(Gtk.Box):
    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-many-public-methods
    __gtype_name__ = "UnlockedDatabase"

    # Connection handlers
    db_locked_handler: int | None = None
    db_save_handler: int | None = None
    clipboard_timer_handler: int | None = None
    _current_element: SafeElement | None = None
    dbus_subscription_id: int | None = None
    _lock_timer_handler: int | None = None
    save_loop: int | None = None  # If int, a thread periodically saves the database

    action_bar = Gtk.Template.Child()
    _edit_page_bin = Gtk.Template.Child()
    _stack = Gtk.Template.Child()
    _unlocked_db_deck = Gtk.Template.Child()
    _unlocked_db_stack = Gtk.Template.Child()

    selection_mode = GObject.Property(type=bool, default=False)

    class Mode(IntEnum):
        ENTRY = 0
        GROUP = 1
        GROUP_EDIT = 2
        SEARCH = 3
        SELECTION = 4

    def __init__(self, window: Window, dbm: DatabaseManager):
        super().__init__()
        # Instances
        self.window: Window = window
        self.database_manager: DatabaseManager = dbm

        root_group = SafeGroup.get_root(dbm)
        self.props.current_element = root_group
        self._mode = self.Mode.GROUP

        # Actionbar has to be setup before edit entry & group headerbars.
        mobile_pathbar = Pathbar(self)
        self.pathbar = Pathbar(self)
        self.action_bar.pack_start(mobile_pathbar)

        # Headerbars
        self.edit_entry_headerbar = EditElementHeaderbar(self, PageType.ENTRY)
        self.edit_group_headerbar = EditElementHeaderbar(self, PageType.GROUP)
        self.search_headerbar = SearchHeaderbar()
        self.selection_mode_headerbar = SelectionModeHeaderbar(self)
        self.headerbar = UnlockedHeaderBar(self)

        self.window.add_headerbar(self.edit_entry_headerbar)
        self.window.add_headerbar(self.edit_group_headerbar)
        self.window.add_headerbar(self.search_headerbar)
        self.window.add_headerbar(self.selection_mode_headerbar)
        self.window.add_headerbar(self.headerbar)

        # self.search has to be loaded after the search headerbar.
        self._search_active = False
        self.search: Search = Search(self)
        self._unlocked_db_stack.add_named(self.search, "search")
        self.search.initialize()

        # Browser Mode
        self.show_browser_page(self.current_element)

        self.setup()

        self.clipboard = Gdk.Display.get_default().get_clipboard()

        self.connect("notify::selection-mode", self._on_selection_mode_changed)
        self.db_locked_handler = self.database_manager.connect(
            "notify::locked", self._on_database_lock_changed
        )
        self.db_save_handler = self.database_manager.connect(
            "save-notification", self.on_database_save_notification
        )

        # Sets the menu's save button sensitive property.
        save_action = window.lookup_action("db.save_dirty")
        dbm.bind_property("is-dirty", save_action, "enabled")

    def do_dispose(self):
        logging.debug("Database disposed")
        self.cleanup()

        if self.db_locked_handler:
            self.database_manager.disconnect(self.db_locked_handler)
            self.db_locked_handler = None

        if self.db_save_handler:
            self.database_manager.disconnect(self.db_save_handler)
            self.db_save_handler = None

        self.search.do_dispose()

        self.edit_entry_headerbar.unparent()
        self.edit_group_headerbar.unparent()
        self.search_headerbar.unparent()
        self.selection_mode_headerbar.unparent()
        self.headerbar.unparent()

    def setup(self):
        self.start_save_loop()
        self.register_dbus_signal()
        self.start_database_lock_timer()

    def listbox_row_factory(self, element: SafeElement) -> Gtk.Widget:
        if element.is_entry:
            return EntryRow(self, element)

        return GroupRow(self, element)

    def show_edit_page(self, element: SafeElement, new: bool = False) -> None:
        self.start_database_lock_timer()
        self.props.current_element = element

        if self.props.search_active:
            self.props.search_active = False

        # Sets the accessed time.
        element.touch()

        if element.is_group:
            page = GroupPage(self)
            self.props.mode = self.Mode.GROUP_EDIT
        else:
            page = EntryPage(self, new)
            self.props.mode = self.Mode.ENTRY

        self._edit_page_bin.set_child(page)
        self._unlocked_db_deck.set_visible_child(self._edit_page_bin)

        # Grab the focus of the Title entry.
        # It is done here so that the Entry has a Window.
        page.name_property_value_entry.grab_focus_without_selecting()

    def show_browser_page(self, group: SafeGroup) -> None:
        self.start_database_lock_timer()
        page_name = group.uuid.urn

        page = self._stack.get_child_by_name(page_name)
        if page:
            self.props.current_element = page.group
        else:
            self.props.current_element = group
            new_page = UnlockedDatabasePage(self, group)
            self._stack.add_named(new_page, page_name)

        self._unlocked_db_stack.set_visible_child(self._stack)
        self._unlocked_db_deck.set_visible_child(self._unlocked_db_stack)
        if not self.props.selection_mode:
            self.props.mode = self.Mode.GROUP

        self._stack.set_visible_child_name(page_name)

    @property
    def in_edit_page(self) -> bool:
        """Returns true if the current visible page is either
        the Group edit page or Entry edit page."""

        boolean: bool = (
            self._unlocked_db_deck.props.visible_child == self._edit_page_bin
        )
        return boolean

    #
    # Headerbar
    #

    def _update_headerbar(self) -> None:
        """Display the correct headerbar according to search state."""
        if self.props.mode == self.Mode.SEARCH:
            self.window.set_headerbar(self.search.headerbar)
        elif self.props.mode == self.Mode.GROUP_EDIT:
            self.window.set_headerbar(self.edit_group_headerbar)
        elif self.props.mode == self.Mode.ENTRY:
            self.window.set_headerbar(self.edit_entry_headerbar)
        elif self.props.mode == self.Mode.SELECTION:
            self.window.set_headerbar(self.selection_mode_headerbar)
        else:
            self.window.set_headerbar(self.headerbar)

    def _on_selection_mode_changed(
        self, _unlocked_database: UnlockedDatabase, _value: GObject.ParamSpec
    ) -> None:
        if self.props.selection_mode:
            self.props.mode = self.Mode.SELECTION

    #
    # Group and Entry Management
    #

    @GObject.Property(type=SafeElement)
    def current_element(self) -> SafeElement:
        return self._current_element

    @current_element.setter  # type: ignore
    def current_element(self, element: SafeElement) -> None:
        self._current_element = element

    def get_current_page(self) -> UnlockedDatabasePage:
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

        if list_box_row.__gtype_name__ == "GroupRow":
            safe_group = list_box_row.safe_group
            self.show_browser_page(safe_group)
        else:
            if self.selection_mode:
                active = list_box_row.selection_checkbox.props.active
                list_box_row.selection_checkbox.props.active = not active
                return

            safe_entry = list_box_row.safe_entry
            self.show_edit_page(safe_entry)

    def on_database_save_notification(
        self, _database_manager: DatabaseManager, saved: bool
    ) -> None:
        if saved:
            self.window.send_notification(_("Safe saved"))
        else:
            self.window.send_notification(_("Could not save Safe"))

    def save_safe(self):
        if self.database_manager.is_dirty is True:
            if self.database_manager.save_running is False:
                self.save_database(notification=True)
            else:
                # NOTE: In-app notification to inform the user that already an unfinished save job is running
                self.window.send_notification(
                    _("Please wait. Another save is running.")
                )
        else:
            # NOTE: In-app notification to inform the user that no save is necessary because there where no changes made
            self.window.send_notification(_("No changes made"))

    def lock_safe(self):
        self.database_manager.props.locked = True

    def on_add_entry_action(self) -> None:
        """CB when the Add Entry menu was clicked"""
        group = self.props.current_element.group
        new_entry: SafeEntry = self.database_manager.add_entry_to_database(group)
        self.show_edit_page(new_entry, new=True)

    def on_add_group_action(self) -> None:
        """CB when menu entry Add Group is clicked"""
        self.database_manager.is_dirty = True
        safe_group = self.database_manager.add_group_to_database(
            "", "0", "", self.props.current_element.group
        )
        self.show_edit_page(safe_group)

    def on_element_delete_action(self) -> None:
        """Delete the visible entry from the menu."""
        parent_group = self.props.current_element.parentgroup
        uuid = self.props.current_element.element.uuid.urn
        self.database_manager.delete_from_database(self.props.current_element.element)

        self.show_browser_page(parent_group)

        page = self._stack.get_child_by_name(uuid)
        if page:
            self._stack.remove(page)

    def on_entry_duplicate_action(self):
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

        self.clipboard.set(text)

        self.window.send_notification(message)

        clear_clipboard_time = passwordsafe.config_manager.get_clear_clipboard()

        def callback():
            self.clipboard_timer_handler = None
            self.clipboard.set_content(None)

        self.clipboard_timer_handler = GLib.timeout_add_seconds(
            clear_clipboard_time, callback
        )

    def show_database_settings(self) -> None:
        DatabaseSettingsDialog(self).present()

    def on_session_lock(
        self, _connection, _unique_name, _object_path, _interface, _signal, state
    ):
        if state[0] and not self.database_manager.props.locked:
            self.lock_timeout_database()

    #
    # Dialog Creator
    #

    def show_references_dialog(self) -> None:
        """Show a Group/Entry reference dialog

        Invoked by the app.entry.references action"""
        ReferencesDialog(self).present()

    def show_properties_dialog(self) -> None:
        """Show a Group/Entry property dialog

        Invoked by the app.element.properties action"""
        PropertiesDialog(self).present()

    #
    # Utils
    #

    def _on_database_lock_changed(self, _database_manager, _value):
        locked = self.database_manager.props.locked
        if locked:
            self.cleanup()
            if passwordsafe.config_manager.get_save_automatically():
                self.save_database()

            filepath = self.database_manager.database_path
            self.window.start_database_opening_routine(filepath)
        else:
            self.window.view = self.window.View.UNLOCKED_DATABASE
            self.setup()
            self._update_headerbar()

    def lock_timeout_database(self):
        self.database_manager.props.locked = True

        # NOTE: Notification that a safe has been locked.
        self.window.send_notification(_("Safe locked due to inactivity"))

    #
    # Helper Methods
    #

    def cleanup(self) -> None:
        """Stop all ongoing operations:

        * stop the save loop
        * cancel all timers
        * unregistrer from dbus

        This is the opposite of setup().
        """
        logging.debug("Cleaning database %s", self.database_manager.database_path)

        if self.clipboard_timer_handler:
            GLib.source_remove(self.clipboard_timer_handler)
            self.clipboard_timer_handler = None
            self.clipboard.set_content(None)

        if self._lock_timer_handler:
            GLib.source_remove(self._lock_timer_handler)
            self._lock_timer_handler = None

        # Do not listen to screensaver kicking in anymore
        if self.dbus_subscription_id:
            connection = Gio.Application.get_default().get_dbus_connection()
            connection.signal_unsubscribe(self.dbus_subscription_id)
            self.dbus_subscription_id = None

        # stop the save loop
        if self.save_loop:
            GLib.source_remove(self.save_loop)
            self.save_loop = None

        # Cleanup temporal files created when opening attachments.
        def callback(gfile, result):
            try:
                success = gfile.delete_finish(result)
                if not success:
                    raise Exception("IO operation error")

            except Exception as err:  # pylint: disable=broad-except
                logging.debug("Could not delete temporal file: %s", err)

        cache_dir = os.path.join(GLib.get_user_cache_dir(), const.SHORT_NAME, "tmp")
        for root, _dirs, files in os.walk(cache_dir):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                gfile = Gio.File.new_for_path(file_path)
                gfile.delete_async(GLib.PRIORITY_DEFAULT, None, callback)

    def save_database(self, notification: bool = False) -> None:
        """Save the database.

        If auto_save is False, a dialog asking for confirmation
        will be displayed.
        """
        if not self.database_manager.is_dirty or self.database_manager.save_running:
            return

        save_thread = threading.Thread(
            target=self.database_manager.save_database, args=[notification]
        )
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
        logging.debug("Starting automatic save loop")
        self.save_loop = GLib.timeout_add_seconds(30, self.threaded_save_loop)

    def threaded_save_loop(self) -> bool:
        """Saves the safe as long as it returns True."""
        if passwordsafe.config_manager.get_save_automatically() is True:
            logging.debug("Automatically saving")
            self.database_manager.save_database()

        return GLib.SOURCE_CONTINUE

    #
    # DBus
    #

    def register_dbus_signal(self) -> None:
        """Register a listener so we get notified about screensave kicking in

        In this case we will call self.on_session_lock()"""
        logging.debug("Subscribed to org.gnome.ScreenSaver")
        connection = Gio.Application.get_default().get_dbus_connection()
        self.dbus_subscription_id = connection.signal_subscribe(
            None,
            "org.gnome.ScreenSaver",
            "ActiveChanged",
            "/org/gnome/ScreenSaver",
            None,
            Gio.DBusSignalFlags.NONE,
            self.on_session_lock,
        )

    def go_back(self):
        if self.props.selection_mode:
            self.props.selection_mode = False
            self.props.mode = self.Mode.GROUP
            return
        if self.props.search_active:
            self.props.search_active = False
            self.props.mode = self.Mode.GROUP
            return
        if self.props.current_element.is_root_group:
            return

        parent = self.props.current_element.parentgroup
        self.show_browser_page(parent)

    @GObject.Property(type=bool, default=False)
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
            self.props.mode = self.Mode.SEARCH
            self._unlocked_db_stack.set_visible_child_name("search")
        else:
            self.show_browser_page(self.current_element)

    @GObject.Property(type=bool, default=False)
    def database_locked(self):
        """Get database lock status

        :returns: True if the database is locked
        :rtype: bool
        """
        return self.database_manager.props.locked

    @GObject.Property(type=int, default=0)
    def mode(self) -> int:
        return self._mode

    @mode.setter  # type: ignore
    def mode(self, new_mode: int) -> None:
        self._mode = new_mode
        self._update_headerbar()
