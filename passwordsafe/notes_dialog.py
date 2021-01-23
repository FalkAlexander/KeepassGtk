# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from gi.repository import Gdk, GObject, Gtk, Handy


class NotesDialog:
    # pylint: disable=too-many-instance-attributes

    def __init__(self, unlocked_database, safe_entry):
        self.__builder = Gtk.Builder()
        self.__builder.add_from_resource("/org/gnome/PasswordSafe/notes_dialog.ui")

        self.__unlocked_database = unlocked_database
        self.__safe_entry = safe_entry
        self.__dialog = self.__builder.get_object("notes_detached_dialog")
        self.__accelerators = Gtk.AccelGroup()
        self.__search_stopped = False

        self.__notes_buffer = self.__builder.get_object("value_entry").get_buffer()
        self.__tag = self.__notes_buffer.create_tag("found", background="yellow")

        self.__setup_widgets()
        self.__setup_signals()
        self.__setup_accelerators()

    def present(self):
        self.__dialog.present()

    def __setup_signals(self):
        self.__unlocked_database.database_manager.connect("notify::locked", self.__on_locked)
        self.__builder.get_object("copy_button").connect("clicked", self.__on_copy_button_clicked)

        # Search
        self.__search_button = self.__builder.get_object("search_button")
        self.__search_bar = self.__builder.get_object("search_bar")
        self.__search_entry = self.__builder.get_object("search_entry")

        self.__search_button.connect("toggled", self.__on_search_button_toggled)
        self.__search_entry.connect("search-changed", self.__on_search_entry_changed)
        self.__search_entry.connect("stop-search", self.__on_search_stopped)

        # Bind text to the corresponding safe entry.
        self.__safe_entry.bind_property(
            "notes", self.__notes_buffer, "text",
            GObject.BindingFlags.SYNC_CREATE
            | GObject.BindingFlags.BIDIRECTIONAL)

    def __setup_widgets(self):
        # Dialog
        self.__dialog.set_modal(True)
        self.__dialog.set_transient_for(self.__unlocked_database.window)
        self.__dialog.connect("key-press-event", self.__on_key_press_event)

    def __setup_accelerators(self):
        self.__dialog.add_accel_group(self.__accelerators)
        self.__add_search_accelerator()
        # TODO Add accelerator for save on "<primary>s"

    def __add_search_accelerator(self):
        key, mod = Gtk.accelerator_parse("<primary>f")
        self.__search_button.add_accelerator(
            "clicked", self.__accelerators, key, mod, Gtk.AccelFlags.VISIBLE
        )

    #
    # Events
    #

    def __on_copy_button_clicked(self, _button):
        notes_buffer = self.__notes_buffer

        self.__unlocked_database.send_to_clipboard(
            notes_buffer.get_text(
                notes_buffer.get_start_iter(), notes_buffer.get_end_iter(), False
            )
        )

    def __on_search_button_toggled(self, _button):
        self.__unlocked_database.start_database_lock_timer()

        if self.__search_stopped is True:
            return
        self.__toggle_search_bar()

    def __toggle_search_bar(self):
        if self.__search_bar.get_search_mode() is True:
            self.__search_bar.set_search_mode(False)
        else:
            self.__search_bar.set_search_mode(True)

    def __on_search_entry_changed(self, entry):
        self.__unlocked_database.start_database_lock_timer()

        notes_buffer = self.__notes_buffer

        notes_buffer.remove_all_tags(
            notes_buffer.get_start_iter(), notes_buffer.get_end_iter()
        )

        start = notes_buffer.get_start_iter()
        if entry.get_text():
            self.__do_search(notes_buffer, entry.get_text(), start)

    def __on_search_stopped(self, _entry):
        self.__search_stopped = True
        self.__search_button.set_active(False)
        self.__search_stopped = False

    #
    # Tools
    #

    def __do_search(self, notes_buffer, keyword, start):
        end = notes_buffer.get_end_iter()
        match = start.forward_search(keyword, Gtk.TextSearchFlags.CASE_INSENSITIVE, end)

        if match is not None:
            match_start, match_end = match
            notes_buffer.apply_tag(self.__tag, match_start, match_end)
            self.__do_search(notes_buffer, keyword, match_end)

    def __on_key_press_event(self, _window: Handy.Window, event: Gtk.Event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            if not self.__search_bar.get_search_mode():
                self.__unlocked_database.start_database_lock_timer()

                self.__dialog.close()
                return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def __on_locked(self, database_manager, _value):
        locked = database_manager.props.locked
        if locked:
            self.__dialog.close()
