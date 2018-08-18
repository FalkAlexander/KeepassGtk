from gi.repository import Gio, Gdk, Gtk
from gi.repository.GdkPixbuf import Pixbuf
from gi.repository import Notify
from passwordsafe.logging_manager import LoggingManager
from passwordsafe.pathbar import Pathbar
from passwordsafe.entry_row import EntryRow
from passwordsafe.group_row import GroupRow
from passwordsafe.scrolled_page import ScrolledPage
from passwordsafe.database_settings_dialog import DatabaseSettingsDialog
from threading import Timer
import passwordsafe.password_generator
import passwordsafe.config_manager
import os
import gi
import ntpath
import datetime

gi.require_version('Gtk', '3.0')


class UnlockedDatabase:
    builder = NotImplemented
    window = NotImplemented
    parent_widget = NotImplemented
    headerbar = NotImplemented
    headerbar_search = NotImplemented
    scrolled_window = NotImplemented
    stack = NotImplemented
    database_manager = NotImplemented
    logging_manager = LoggingManager(True)
    current_group = NotImplemented
    pathbar = NotImplemented
    overlay = NotImplemented
    search_overlay = NotImplemented
    accelerators = NotImplemented
    scheduled_page_destroy = []
    clipboard = NotImplemented
    list_box_sorting = NotImplemented
    clipboard_timer = NotImplemented
    database_lock_timer = NotImplemented
    search_list_box = NotImplemented
    selection_mode = False
    unlock_database = NotImplemented
    search = False

    entry_marked_for_delete = NotImplemented
    group_marked_for_delete = NotImplemented
    group_marked_for_edit = NotImplemented

    entries_selected = []
    groups_selected = []

    def __init__(self, window, widget, dbm, unlock_database):
        self.window = window
        self.parent_widget = widget
        self.database_manager = dbm
        self.unlock_database = unlock_database
        self.assemble_listbox()
        self.window.opened_databases.append(self)

    #
    # Stack Pages
    #

    def assemble_listbox(self):
        self.builder = Gtk.Builder()
        self.builder.add_from_resource("/org/gnome/PasswordSafe/unlocked_database.ui")

        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        self.accelerators = Gtk.AccelGroup()
        self.window.add_accel_group(self.accelerators)

        self.overlay = Gtk.Overlay()
        self.parent_widget.add(self.overlay)

        database_action_overlay = self.builder.get_object("database_action_overlay")
        self.overlay.add_overlay(database_action_overlay)

        self.current_group = self.database_manager.get_root_group()

        self.stack = self.builder.get_object("list_stack")
        self.overlay.add(self.stack)
        self.overlay.show_all()

        self.set_headerbar()
        self.prepare_actions()

        self.list_box_sorting = passwordsafe.config_manager.get_sort_order()
        self.start_database_lock_timer()

        self.show_page_of_new_directory(False, False)

    #
    # Headerbar
    #

    # Assemble headerbar
    def set_headerbar(self):
        self.headerbar = self.builder.get_object("headerbar")

        save_button = self.builder.get_object("save_button")
        save_button.connect("clicked", self.on_save_button_clicked)
        self.bind_accelerator(self.accelerators, save_button, "<Control>s")

        lock_button = self.builder.get_object("lock_button")
        lock_button.connect("clicked", self.on_lock_button_clicked)
        self.bind_accelerator(self.accelerators, lock_button, "<Control>l")

        mod_box = self.builder.get_object("mod_box")
        browser_buttons_box = self.builder.get_object("browser_buttons_box")
        mod_box.add(browser_buttons_box)

        search_button = self.builder.get_object("search_button")
        search_button.connect("clicked", self.set_search_headerbar)
        self.bind_accelerator(self.accelerators, search_button, "<Control>f")

        selection_button = self.builder.get_object("selection_button")
        selection_button.connect("clicked", self.set_selection_headerbar)

        add_entry_button = self.builder.get_object("add_entry_button")
        add_entry_button.connect("clicked", self.on_add_entry_button_clicked)

        add_group_button = self.builder.get_object("add_group_button")
        add_group_button.connect("clicked", self.on_add_group_button_clicked)

        add_property_button = self.builder.get_object("add_property_button")
        add_property_button.connect("clicked", self.on_add_property_button_clicked)

        # Search Headerbar
        headerbar_search_box_close_button = self.builder.get_object("headerbar_search_box_close_button")
        headerbar_search_box_close_button.connect("clicked", self.on_headerbar_search_close_button_clicked)

        search_settings_popover_local_button = self.builder.get_object("search_settings_popover_local_button")
        search_settings_popover_fulltext_button = self.builder.get_object("search_settings_popover_fulltext_button")

        search_local_button = self.builder.get_object("search_local_button")
        search_local_button.connect("toggled", self.on_search_filter_button_toggled)

        search_fulltext_button = self.builder.get_object("search_fulltext_button")
        search_fulltext_button.connect("toggled", self.on_search_filter_button_toggled)

        headerbar_search_entry = self.builder.get_object("headerbar_search_entry")
        headerbar_search_entry.connect("changed", self.on_headerbar_search_entry_changed, search_local_button, search_fulltext_button)
        headerbar_search_entry.connect("activate", self.on_headerbar_search_entry_enter_pressed)

        # Selection Headerbar
        selection_cancel_button = self.builder.get_object("selection_cancel_button")
        selection_cancel_button.connect("clicked", self.on_selection_cancel_button_clicked)

        selection_delete_button = self.builder.get_object("selection_delete_button")
        selection_delete_button.connect("clicked", self.on_selection_delete_button_clicked)

        selection_cut_button = self.builder.get_object("selection_cut_button")
        selection_cut_button.connect("clicked", self.on_selection_cut_button_clicked)

        self.set_gio_actions()

        self.parent_widget.set_headerbar(self.headerbar)
        self.window.set_titlebar(self.headerbar)

        self.pathbar = Pathbar(self, self.database_manager, self.database_manager.get_root_group(), self.headerbar)

    def set_gio_actions(self):
        db_settings_action = Gio.SimpleAction.new("db.settings", None)
        db_settings_action.connect("activate", self.on_database_settings_entry_clicked)

        az_button_action = Gio.SimpleAction.new("sort.az", None)
        az_button_action.connect("activate", self.on_sort_menu_button_entry_clicked, "A-Z")

        za_button_action = Gio.SimpleAction.new("sort.za", None)
        za_button_action.connect("activate", self.on_sort_menu_button_entry_clicked, "Z-A")

        last_added_button_action = Gio.SimpleAction.new("sort.last_added", None)
        last_added_button_action.connect("activate", self.on_sort_menu_button_entry_clicked, "last_added")

        selection_all_action = Gio.SimpleAction.new("selection.all", None)
        selection_all_action.connect("activate", self.on_selection_popover_button_clicked, "all")

        selection_none_action = Gio.SimpleAction.new("selection.none", None)
        selection_none_action.connect("activate", self.on_selection_popover_button_clicked, "none")

        self.window.application.add_action(db_settings_action)
        self.window.application.add_action(az_button_action)
        self.window.application.add_action(za_button_action)
        self.window.application.add_action(last_added_button_action)
        self.window.application.add_action(selection_all_action)
        self.window.application.add_action(selection_none_action)

    # Selection headerbar
    def set_selection_headerbar(self, widget):
        self.builder.get_object("selection_delete_button").set_sensitive(False)
        self.builder.get_object("selection_cut_button").set_sensitive(False)

        selection_options_button = self.builder.get_object("selection_options_button")
        selection_button_box = self.builder.get_object("selection_button_box")

        title_box = self.builder.get_object("title_box")
        headerbar_right_box = self.builder.get_object("headerbar_right_box")

        linkedbox_right = self.builder.get_object("linkedbox_right")

        headerbar_right_box.remove(linkedbox_right)
        headerbar_right_box.add(selection_button_box)
        title_box.add(selection_options_button)

        context = self.headerbar.get_style_context()
        context.add_class('selection-mode')
        self.headerbar.set_show_close_button(False)

        for element in self.pathbar.get_children():
            if element.get_name() == "SeperatorLabel":
                el_context = element.get_style_context()
                el_context.add_class('SeperatorLabelSelectedMode')

        self.selection_mode = True

        self.prepare_selection_page()

    def remove_selection_headerbar(self):
        for stack_page in self.stack.get_children():
            if stack_page.check_is_edit_page() is False:
                stack_page.destroy()

        selection_options_button = self.builder.get_object("selection_options_button")
        selection_button_box = self.builder.get_object("selection_button_box")

        title_box = self.builder.get_object("title_box")
        headerbar_right_box = self.builder.get_object("headerbar_right_box")

        linkedbox_right = self.builder.get_object("linkedbox_right")

        headerbar_right_box.remove(selection_button_box)
        headerbar_right_box.add(linkedbox_right)
        title_box.remove(selection_options_button)
        self.headerbar.set_show_close_button(True)

        context = self.headerbar.get_style_context()
        context.remove_class('selection-mode')

        self.entries_selected.clear()
        self.groups_selected.clear()

        for element in self.pathbar.get_children():
            if element.get_name() == "SeperatorLabel":
                el_context = element.get_style_context()
                el_context.remove_class('SeperatorLabelSelectedMode')
                el_context.add_class('SeperatorLabel')

        self.selection_mode = False
        self.show_page_of_new_directory(False, False)

    # Search headerbar
    def set_search_headerbar(self, widget):
        hscb = self.builder.get_object("headerbar_search_box_close_button")
        if hscb.get_active() is False:
            hscb.set_active(True)

        self.headerbar_search = self.builder.get_object("headerbar_search")
        self.parent_widget.set_headerbar(self.headerbar_search)
        self.window.set_titlebar(self.headerbar_search)
        self.builder.get_object("headerbar_search_entry").grab_focus()
        self.builder.get_object("headerbar_search_entry").connect("key-release-event", self.on_search_entry_esc_key)
        self.search = True

        self.prepare_search_page()

    def remove_search_headerbar(self, widget):
        self.parent_widget.set_headerbar(self.headerbar)
        self.window.set_titlebar(self.headerbar)
        self.search = False

    # Group and entry browser headerbar
    def set_browser_headerbar(self):
        mod_box = self.builder.get_object("mod_box")

        for child in mod_box.get_children():
            mod_box.remove(child)

        mod_box.add(self.builder.get_object("browser_buttons_box"))

    # Entry creation/editing page headerbar
    def set_entry_page_headerbar(self):
        mod_box = self.builder.get_object("mod_box")

        for child in mod_box.get_children():
            mod_box.remove(child)

        mod_box.add(self.builder.get_object("entry_page_mod_box"))

        entry_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.current_group)
        scrolled_page = self.stack.get_child_by_name(entry_uuid)
        if scrolled_page.add_button_disabled is True:
            self.builder.get_object("add_property_button").set_sensitive(False)
        else:
            self.builder.get_object("add_property_button").set_sensitive(True)

    # Group creation/editing headerbar
    def set_group_edit_page_headerbar(self):
        mod_box = self.builder.get_object("mod_box")

        for child in mod_box.get_children():
            mod_box.remove(child)

    # Actions for MenuButton Popover
    def prepare_actions(self):
        delete_entry_action = Gio.SimpleAction.new("entry.delete", None)
        delete_entry_action.connect("activate", self.on_entry_delete_menu_button_clicked)
        self.window.application.add_action(delete_entry_action)

        edit_group_action = Gio.SimpleAction.new("group.edit", None)
        edit_group_action.connect("activate", self.on_group_edit_menu_button_clicked)
        self.window.application.add_action(edit_group_action)

        delete_group_action = Gio.SimpleAction.new("group.delete", None)
        delete_group_action.connect("activate", self.on_group_delete_menu_button_clicked)
        self.window.application.add_action(delete_group_action)

    # Set Search stack page
    def prepare_search_page(self):
        if self.stack.get_child_by_name("search") is None:
            scrolled_page = ScrolledPage(False)
            viewport = Gtk.Viewport()
            self.search_overlay = Gtk.Overlay()
            builder = Gtk.Builder()
            builder.add_from_resource("/org/gnome/PasswordSafe/unlocked_database.ui")
            self.search_list_box = builder.get_object("list_box")
            self.search_list_box.connect("row-activated", self.on_list_box_row_activated)
            viewport.add(self.search_overlay)
            self.search_overlay.add(self.search_list_box)
            scrolled_page.add(viewport)
            scrolled_page.show_all()
            self.stack.add_named(scrolled_page, "search")
            if len(self.search_list_box.get_children()) is 0:
                info_search_overlay = self.builder.get_object("info_search_overlay")
                self.search_overlay.add_overlay(info_search_overlay)

        self.stack.set_visible_child(self.stack.get_child_by_name("search"))

    def prepare_selection_page(self):
        for stack_page in self.stack.get_children():
            if stack_page.check_is_edit_page() is False:
                stack_page.destroy()
        self.show_page_of_new_directory(False, False)

    #
    # Keystrokes
    #

    def bind_accelerator(self, accelerators, widget, accelerator, signal="clicked"):
        key, mod = Gtk.accelerator_parse(accelerator)
        widget.add_accelerator(signal, accelerators, key, mod, Gtk.AccelFlags.VISIBLE)

    #
    # Group and Entry Management
    #

    def show_page_of_new_directory(self, edit_group, new_entry):
        # First, remove stack pages which should not exist because they are scheduled for remove
        self.destroy_scheduled_stack_page()

        # Check if we need to remove the search headerbar
        if self.parent_widget.get_headerbar() is not self.headerbar:
            self.remove_search_headerbar(None)

        # Creation of group edit page
        if edit_group is True:
            self.destroy_scheduled_stack_page()

            builder = Gtk.Builder()
            builder.add_from_resource("/org/gnome/PasswordSafe/group_page.ui")

            scrolled_window = ScrolledPage(True)

            viewport = Gtk.Viewport()
            scrolled_window.properties_list_box = builder.get_object("properties_list_box")
            viewport.add(scrolled_window.properties_list_box)
            scrolled_window.add(viewport)
            scrolled_window.show_all()

            stack_page_uuid = self.database_manager.get_group_uuid_from_group_object(self.current_group)
            if self.stack.get_child_by_name(stack_page_uuid) is not None:
                stack_page = self.stack.get_child_by_name(stack_page_uuid)
                stack_page.destroy()

            self.add_stack_page(scrolled_window)
            self.insert_group_properties_into_listbox(scrolled_window.properties_list_box)
            self.set_group_edit_page_headerbar()     
        # If the stack page with current group's uuid isn't existing - we need to create it (first time opening of group/entry)       
        elif self.stack.get_child_by_name(self.database_manager.get_group_uuid_from_group_object(self.current_group)) is None and self.stack.get_child_by_name(self.database_manager.get_entry_uuid_from_entry_object(self.current_group)) is None and edit_group is False:
            # Create not existing stack page for group
            if self.database_manager.check_is_group(self.database_manager.get_group_uuid_from_group_object(self.current_group)) is True:
                builder = Gtk.Builder()
                builder.add_from_resource("/org/gnome/PasswordSafe/unlocked_database.ui")
                list_box = builder.get_object("list_box")
                list_box.connect("row-activated", self.on_list_box_row_activated)

                scrolled_window = ScrolledPage(False)
                viewport = Gtk.Viewport()
                overlay = Gtk.Overlay()
                overlay.add(list_box)
                viewport.add(overlay)
                scrolled_window.add(viewport)
                scrolled_window.show_all()

                self.add_stack_page(scrolled_window)
                self.insert_groups_into_listbox(list_box)
                self.insert_entries_into_listbox(list_box)

                if len(list_box.get_children()) is 0:
                    empty_group_overlay = builder.get_object("empty_group_overlay")
                    overlay.add_overlay(empty_group_overlay)
            # Create not existing stack page for entry
            else:
                builder = Gtk.Builder()
                builder.add_from_resource("/org/gnome/PasswordSafe/entry_page.ui")

                scrolled_window = ScrolledPage(True)

                viewport = Gtk.Viewport()
                scrolled_window.properties_list_box = builder.get_object("properties_list_box")
                viewport.add(scrolled_window.properties_list_box)
                scrolled_window.add(viewport)
                scrolled_window.show_all()

                self.add_stack_page(scrolled_window)
                if new_entry is True:
                    self.insert_entry_properties_into_listbox(scrolled_window.properties_list_box, True)
                else:
                    self.insert_entry_properties_into_listbox(scrolled_window.properties_list_box, False)
        # Stack page with current group's uuid already exists, we only need to switch stack page
        else:
            # For group
            if self.database_manager.check_is_group(self.database_manager.get_group_uuid_from_group_object(self.current_group)) is True:
                self.stack.set_visible_child_name(self.database_manager.get_group_uuid_from_group_object(self.current_group))
                self.set_browser_headerbar()
            # For entry
            else:
                self.stack.set_visible_child_name(self.database_manager.get_entry_uuid_from_entry_object(self.current_group))
                self.set_entry_page_headerbar()

    def add_stack_page(self, scrolled_window):
        if self.database_manager.check_is_group(self.database_manager.get_group_uuid_from_group_object(self.current_group)) is True:
            self.stack.add_named(scrolled_window, self.database_manager.get_group_uuid_from_group_object(self.current_group))
        else:
            self.stack.add_named(scrolled_window, self.database_manager.get_entry_uuid_from_entry_object(self.current_group))

        self.switch_stack_page()

    def switch_stack_page(self):
        page_uuid = NotImplemented

        if self.database_manager.check_is_group(self.database_manager.get_group_uuid_from_group_object(self.current_group)) is True:
            page_uuid = self.database_manager.get_group_uuid_from_group_object(self.current_group)
            self.set_browser_headerbar()
        else:
            page_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.current_group)
            self.set_entry_page_headerbar()

        if page_uuid in self.scheduled_page_destroy:
            stack_page = self.stack.get_child_by_name(page_uuid)

            if stack_page is not None:
                stack_page.destroy()
                
            self.scheduled_page_destroy.remove(page_uuid)
            self.show_page_of_new_directory(False, False)

        if self.stack.get_child_by_name(page_uuid) is None:
            self.show_page_of_new_directory(False, False)
        else:
            self.stack.set_visible_child_name(page_uuid)

    def update_current_stack_page(self):
        stack_page_name = self.database_manager.get_group_uuid_from_group_object(self.current_group)
        stack_page = self.stack.get_child_by_name(stack_page_name)
        stack_page.destroy()
        self.show_page_of_new_directory(False, False)

    def set_current_group(self, group):
        self.current_group = group

    def get_current_group(self):
        return self.current_group

    def schedule_stack_page_for_destroy(self, page_name):
        self.scheduled_page_destroy.append(page_name)

    def destroy_scheduled_stack_page(self):
        page_uuid = NotImplemented
        if self.database_manager.check_is_group(self.database_manager.get_group_uuid_from_group_object(self.current_group)) is True:
            page_uuid = self.database_manager.get_group_uuid_from_group_object(self.current_group)
        else:
            page_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.current_group)

        if page_uuid in self.scheduled_page_destroy:
            stack_page_name = self.stack.get_child_by_name(page_uuid)
            if stack_page_name is not None:
                stack_page_name.destroy()
            self.scheduled_page_destroy.remove(page_uuid)

    #
    # Create Group & Entry Rows
    #

    def insert_groups_into_listbox(self, list_box):
        groups = NotImplemented
        sorted_list = []

        if self.current_group.is_root_group:
            groups = self.database_manager.get_groups_in_root()
        else:
            groups = self.database_manager.get_groups_in_folder(self.database_manager.get_group_uuid_from_group_object(self.current_group))

        for group in groups:
            group_row = GroupRow(self, self.database_manager, group)
            sorted_list.append(group_row)
        if self.list_box_sorting == "A-Z":
            sorted_list.sort(key=lambda group: str.lower(group.label), reverse=False)
        elif self.list_box_sorting == "Z-A":
            sorted_list.sort(key=lambda group: str.lower(group.label), reverse=True)

        for group_row in sorted_list:
            list_box.add(group_row)

    def insert_entries_into_listbox(self, list_box):
        entries = self.database_manager.get_entries_in_folder(self.database_manager.get_group_uuid_from_group_object(self.current_group))
        sorted_list = []

        for entry in entries:
            entry_row = EntryRow(self, self.database_manager, entry)
            sorted_list.append(entry_row)

        if self.list_box_sorting == "A-Z":
            sorted_list.sort(key=lambda entry: str.lower(entry.label), reverse=False)
        elif self.list_box_sorting == "Z-A":
            sorted_list.sort(key=lambda entry: str.lower(entry.label), reverse=True)

        for entry_row in sorted_list:
            list_box.add(entry_row)

    def rebuild_all_pages(self):
        for page in self.stack.get_children():
            if page.check_is_edit_page() is False:
                page.destroy()

        self.show_page_of_new_directory(False, False)
        
    #
    # Create Property Rows
    #

    def insert_entry_properties_into_listbox(self, properties_list_box, add_all):
        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/PasswordSafe/entry_page.ui")

        entry_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.current_group)
        scrolled_page = self.stack.get_child_by_name(entry_uuid)

        if self.database_manager.has_entry_name(entry_uuid) is True or add_all is True:
            if scrolled_page.name_property_row is NotImplemented:
                scrolled_page.name_property_row = builder.get_object("name_property_row")
                scrolled_page.name_property_value_entry = builder.get_object("name_property_value_entry")
                value = self.database_manager.get_entry_name_from_entry_uuid(entry_uuid)
                if self.database_manager.has_entry_name(entry_uuid) is True:
                    scrolled_page.name_property_value_entry.set_text(value)
                else:
                    scrolled_page.name_property_value_entry.set_text("")

                scrolled_page.name_property_value_entry.connect("changed", self.on_property_value_entry_changed, "name")
                properties_list_box.add(scrolled_page.name_property_row)
            elif scrolled_page.name_property_row is not "":
                value = self.database_manager.get_entry_name_from_entry_uuid(entry_uuid)
                if self.database_manager.has_entry_name(entry_uuid) is True:
                    scrolled_page.name_property_value_entry.set_text(value)
                else:
                    scrolled_page.name_property_value_entry.set_text("")

                scrolled_page.name_property_value_entry.connect("changed", self.on_property_value_entry_changed, "name")
                properties_list_box.add(scrolled_page.name_property_row)

        if self.database_manager.has_entry_username(entry_uuid) is True or add_all is True:
            if scrolled_page.username_property_row is NotImplemented:
                scrolled_page.username_property_row = builder.get_object("username_property_row")
                scrolled_page.username_property_value_entry = builder.get_object("username_property_value_entry")
                value = self.database_manager.get_entry_username_from_entry_uuid(entry_uuid)
                if self.database_manager.has_entry_username(entry_uuid) is True:
                    scrolled_page.username_property_value_entry.set_text(value)
                else:
                    scrolled_page.username_property_value_entry.set_text("")

                scrolled_page.username_property_value_entry.connect("icon-press", self.on_copy_secondary_button_clicked)
                scrolled_page.username_property_value_entry.connect("changed", self.on_property_value_entry_changed, "username")
                properties_list_box.add(scrolled_page.username_property_row)
            elif scrolled_page.username_property_row is not "":
                value = self.database_manager.get_entry_username_from_entry_uuid(entry_uuid)
                if self.database_manager.has_entry_username(entry_uuid) is True:
                    scrolled_page.username_property_value_entry.set_text(value)
                else:
                    scrolled_page.username_property_value_entry.set_text("")

                scrolled_page.username_property_value_entry.connect("icon-press", self.on_copy_secondary_button_clicked)
                scrolled_page.username_property_value_entry.connect("changed", self.on_property_value_entry_changed, "username")
                properties_list_box.add(scrolled_page.username_property_row)

        if self.database_manager.has_entry_password(entry_uuid) is True or add_all is True:                
            if scrolled_page.password_property_row is NotImplemented:
                scrolled_page.password_property_row = builder.get_object("password_property_row")
                scrolled_page.password_property_value_entry = builder.get_object("password_property_value_entry")
                scrolled_page.show_password_button = builder.get_object("show_password_button")
                scrolled_page.generate_password_button = builder.get_object("generate_password_button")
                value = self.database_manager.get_entry_password_from_entry_uuid(entry_uuid)

                if self.database_manager.has_entry_password(entry_uuid) is True:
                    scrolled_page.password_property_value_entry.set_text(value)
                else:
                    scrolled_page.password_property_value_entry.set_text("")

                scrolled_page.password_property_value_entry.connect("icon-press", self.on_copy_secondary_button_clicked)
                scrolled_page.password_property_value_entry.connect("copy-clipboard", self.on_password_entry_copy_clipboard, None)
                self.bind_accelerator(self.accelerators, scrolled_page.password_property_value_entry, "<Control><Shift>c", signal="copy-clipboard")
                scrolled_page.password_property_value_entry.connect("changed", self.on_property_value_entry_changed, "password")

                self.change_password_entry_visibility(scrolled_page.password_property_value_entry, scrolled_page.show_password_button)
                self.show_generate_password_popover(scrolled_page.generate_password_button, scrolled_page.password_property_value_entry)

                properties_list_box.add(scrolled_page.password_property_row)
            elif scrolled_page.password_property_row is not "":
                value = self.database_manager.get_entry_password_from_entry_uuid(entry_uuid)
                if self.database_manager.has_entry_password(entry_uuid) is True:
                    scrolled_page.password_property_value_entry.set_text(value)
                else:
                    scrolled_page.password_property_value_entry.set_text("")

                scrolled_page.password_property_value_entry.connect("icon-press", self.on_copy_secondary_button_clicked)
                scrolled_page.password_property_value_entry.connect("changed", self.on_property_value_entry_changed, "password")
                properties_list_box.add(scrolled_page.password_property_row)

        if self.database_manager.has_entry_url(entry_uuid) is True or add_all is True:
            if scrolled_page.url_property_row is NotImplemented:
                scrolled_page.url_property_row = builder.get_object("url_property_row")
                scrolled_page.url_property_value_entry = builder.get_object("url_property_value_entry")
                value = self.database_manager.get_entry_url_from_entry_uuid(entry_uuid)
                if self.database_manager.has_entry_url(entry_uuid) is True:
                    scrolled_page.url_property_value_entry.set_text(value)
                else:
                    scrolled_page.url_property_value_entry.set_text("")

                scrolled_page.url_property_value_entry.connect("icon-press", self.on_link_secondary_button_clicked)
                scrolled_page.url_property_value_entry.connect("changed", self.on_property_value_entry_changed, "url")
                properties_list_box.add(scrolled_page.url_property_row)
            elif scrolled_page.url_property_row is not "":
                value = self.database_manager.get_entry_url_from_entry_uuid(entry_uuid)
                if self.database_manager.has_entry_url(entry_uuid) is True:
                    scrolled_page.url_property_value_entry.set_text(value)
                else:
                    scrolled_page.url_property_value_entry.set_text("")

                scrolled_page.url_property_value_entry.connect("icon-press", self.on_link_secondary_button_clicked)
                scrolled_page.url_property_value_entry.connect("changed", self.on_property_value_entry_changed, "url")
                properties_list_box.add(scrolled_page.url_property_row)

        if self.database_manager.has_entry_notes(entry_uuid) is True or add_all is True:
            if scrolled_page.notes_property_row is NotImplemented:
                scrolled_page.notes_property_row = builder.get_object("notes_property_row")
                scrolled_page.notes_property_value_entry = builder.get_object("notes_property_value_entry")
                buffer = scrolled_page.notes_property_value_entry.get_buffer()
                value = self.database_manager.get_entry_notes_from_entry_uuid(entry_uuid)
                if self.database_manager.has_entry_notes(entry_uuid) is True:
                    buffer.set_text(value)
                else:
                    buffer.set_text("")
                buffer.connect("changed", self.on_property_value_entry_changed, "notes")
                properties_list_box.add(scrolled_page.notes_property_row)
            elif scrolled_page.notes_property_row is not "":
                value = self.database_manager.get_entry_notes_from_entry_uuid(entry_uuid)
                buffer = scrolled_page.notes_property_value_entry.get_buffer()
                if self.database_manager.has_entry_notes(entry_uuid) is True:
                    buffer.set_text(value)
                else:
                    buffer.set_text("")
                buffer.connect("changed", self.on_property_value_entry_changed, "notes")
                properties_list_box.add(scrolled_page.notes_property_row)

        if self.database_manager.has_entry_color(entry_uuid) is True or add_all is True:
            if scrolled_page.color_property_row is NotImplemented:
                scrolled_page.color_property_row = builder.get_object("color_property_row")

                scrolled_page.none_button = builder.get_object("none_button")
                scrolled_page.orange_button = builder.get_object("orange_button")
                scrolled_page.green_button = builder.get_object("green_button")
                scrolled_page.blue_button = builder.get_object("blue_button")
                scrolled_page.red_button = builder.get_object("red_button")
                scrolled_page.purple_button = builder.get_object("purple_button")
                scrolled_page.brown_button = builder.get_object("brown_button")

                scrolled_page.none_button.connect("toggled", self.on_entry_color_button_toggled)
                scrolled_page.orange_button.connect("toggled", self.on_entry_color_button_toggled)
                scrolled_page.green_button.connect("toggled", self.on_entry_color_button_toggled)
                scrolled_page.blue_button.connect("toggled", self.on_entry_color_button_toggled)
                scrolled_page.red_button.connect("toggled", self.on_entry_color_button_toggled)
                scrolled_page.purple_button.connect("toggled", self.on_entry_color_button_toggled)
                scrolled_page.brown_button.connect("toggled", self.on_entry_color_button_toggled)

                scrolled_page.none_button.get_children()[0].hide()
                scrolled_page.orange_button.get_children()[0].hide()
                scrolled_page.green_button.get_children()[0].hide()
                scrolled_page.blue_button.get_children()[0].hide()
                scrolled_page.red_button.get_children()[0].hide()
                scrolled_page.purple_button.get_children()[0].hide()
                scrolled_page.brown_button.get_children()[0].hide()

                color = self.database_manager.get_entry_color_from_entry_uuid(entry_uuid)

                if color == "NoneColorButton":
                    scrolled_page.none_button.set_active(True)
                    scrolled_page.none_button.get_children()[0].show_all()
                if color == "BlueColorButton":
                    scrolled_page.blue_button.set_active(True)
                    scrolled_page.blue_button.get_children()[0].show_all()
                if color == "GreenColorButton":
                    scrolled_page.green_button.set_active(True)
                    scrolled_page.green_button.get_children()[0].show_all()
                if color == "OrangeColorButton":
                    scrolled_page.orange_button.set_active(True)
                    scrolled_page.orange_button.get_children()[0].show_all()
                if color == "RedColorButton":
                    scrolled_page.red_button.set_active(True)
                    scrolled_page.red_button.get_children()[0].show_all()
                if color == "PurpleColorButton":
                    scrolled_page.purple_button.set_active(True)
                    scrolled_page.purple_button.get_children()[0].show_all()
                if color == "BrownColorButton":
                    scrolled_page.brown_button.set_active(True)
                    scrolled_page.brown_button.get_children()[0].show_all()

                properties_list_box.add(scrolled_page.color_property_row)
            elif scrolled_page.color_property_row is not NotImplemented:
                properties_list_box.add(scrolled_page.color_property_row)

        if self.database_manager.has_entry_icon(entry_uuid) is True or add_all is True:
            if scrolled_page.icon_property_row is NotImplemented:
                scrolled_page.icon_property_row = builder.get_object("icon_property_row")

                scrolled_page.mail_icon_button = builder.get_object("19")
                scrolled_page.profile_icon_button = builder.get_object("9")
                scrolled_page.network_profile_button = builder.get_object("1")
                scrolled_page.key_button = builder.get_object("0")
                scrolled_page.terminal_icon_button = builder.get_object("30")
                scrolled_page.setting_icon_button = builder.get_object("34")
                scrolled_page.folder_icon_button = builder.get_object("48")
                scrolled_page.harddrive_icon_button = builder.get_object("27")
                scrolled_page.wifi_icon_button = builder.get_object("12")
                scrolled_page.desktop_icon_button = builder.get_object("23")

                entry_icon = self.database_manager.get_entry_icon_from_entry_uuid(entry_uuid)
                if entry_icon == "19":
                    scrolled_page.mail_icon_button.set_active(True)
                if entry_icon == "9":
                    scrolled_page.profile_icon_button.set_active(True)
                if entry_icon == "1":
                    scrolled_page.network_profile_button.set_active(True)
                if entry_icon == "0":
                    scrolled_page.key_button.set_active(True)
                if entry_icon == "30":
                    scrolled_page.terminal_icon_button.set_active(True)
                if entry_icon == "34":
                    scrolled_page.setting_icon_button.set_active(True)
                if entry_icon == "48":
                    scrolled_page.folder_icon_button.set_active(True)
                if entry_icon == "27":
                    scrolled_page.harddrive_icon_button.set_active(True)
                if entry_icon == "12":
                    scrolled_page.wifi_icon_button.set_active(True)
                if entry_icon == "23":
                    scrolled_page.desktop_icon_button.set_active(True)

                scrolled_page.mail_icon_button.connect("toggled", self.on_entry_icon_button_toggled)
                scrolled_page.profile_icon_button.connect("toggled", self.on_entry_icon_button_toggled)
                scrolled_page.network_profile_button.connect("toggled", self.on_entry_icon_button_toggled)
                scrolled_page.key_button.connect("toggled", self.on_entry_icon_button_toggled)
                scrolled_page.terminal_icon_button.connect("toggled", self.on_entry_icon_button_toggled)
                scrolled_page.setting_icon_button.connect("toggled", self.on_entry_icon_button_toggled)
                scrolled_page.folder_icon_button.connect("toggled", self.on_entry_icon_button_toggled)
                scrolled_page.harddrive_icon_button.connect("toggled", self.on_entry_icon_button_toggled)
                scrolled_page.wifi_icon_button.connect("toggled", self.on_entry_icon_button_toggled)
                scrolled_page.desktop_icon_button.connect("toggled", self.on_entry_icon_button_toggled)

                properties_list_box.add(scrolled_page.icon_property_row)
            elif scrolled_page.icon_property_row is not NotImplemented:
                properties_list_box.add(scrolled_page.icon_property_row)

        if scrolled_page.color_property_row is not NotImplemented and scrolled_page.name_property_row is not NotImplemented and scrolled_page.username_property_row is not NotImplemented and scrolled_page.password_property_row is not NotImplemented and scrolled_page.url_property_row is not NotImplemented and scrolled_page.notes_property_row is not NotImplemented:
            scrolled_page.add_button_disabled = True
            self.builder.get_object("add_property_button").set_sensitive(False)

    def build_expiry_row(self, expiry):
        entry_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.current_group)
        scrolled_page = self.stack.get_child_by_name(self.database_manager.get_entry_uuid_from_entry_object(self.current_group))
        
        if expiry is False:
            scrolled_page.date_button.set_sensitive(False)
            scrolled_page.time_button.set_sensitive(False)
        else:
            scrolled_page.expiry_control_button_image.set_from_icon_name("user-trash-symbolic", 16)
            scrolled_page.data_button.set_sensitive(True)
            scrolled_page.time_button.set_sensitive(True)
            date_label.set_text(self.database_manager.get_entry_expiry_date_from_entry_uuid(entry_uuid))
            time_label.set_text(self.database_manager.get_entry_expiry_date_from_entry_uuid(entry_uuid))  

    def insert_group_properties_into_listbox(self, properties_list_box):
        group_uuid = self.database_manager.get_group_uuid_from_group_object(self.current_group)

        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/PasswordSafe/group_page.ui")

        name_property_row = builder.get_object("name_property_row")
        name_property_value_entry = builder.get_object("name_property_value_entry")
        name_property_value_entry.connect("changed", self.on_property_value_group_changed, "name")

        notes_property_row = builder.get_object("notes_property_row")
        notes_property_value_entry = builder.get_object("notes_property_value_entry")
        buffer = notes_property_value_entry.get_buffer()
        buffer.connect("changed", self.on_property_value_group_changed, "notes")

        name_value = self.database_manager.get_group_name_from_uuid(group_uuid)
        notes_value = self.database_manager.get_group_notes_from_group_uuid(group_uuid)

        if self.database_manager.has_group_name(group_uuid) is True:
            name_property_value_entry.set_text(name_value)
        else:
            name_property_value_entry.set_text("")

        if self.database_manager.has_group_notes(group_uuid) is True:
            buffer.set_text(notes_value)
        else:
            buffer.set_text("")

        properties_list_box.add(name_property_row)
        properties_list_box.add(notes_property_row)

    #
    # Events
    #

    def on_list_box_row_activated(self, widget, list_box_row):
        self.start_database_lock_timer()

        if list_box_row.get_type() == "EntryRow" and self.selection_mode is True:
            if list_box_row.selection_checkbox.get_active():
                list_box_row.selection_checkbox.set_active(False)
            else:
                list_box_row.selection_checkbox.set_active(True)
        elif list_box_row.get_type() == "EntryRow" and self.selection_mode is not True:
            self.set_current_group(self.database_manager.get_entry_object_from_uuid(list_box_row.get_entry_uuid()))
            self.pathbar.add_pathbar_button_to_pathbar(list_box_row.get_entry_uuid())
            self.show_page_of_new_directory(False, False)
        elif list_box_row.get_type() == "GroupRow":
            self.set_current_group(self.database_manager.get_group_object_from_uuid(list_box_row.get_group_uuid()))
            self.pathbar.add_pathbar_button_to_pathbar(list_box_row.get_group_uuid())
            self.show_page_of_new_directory(False, False)

    def on_save_button_clicked(self, widget):
        self.start_database_lock_timer()
        self.database_manager.save_database()
        self.show_database_action_revealer("Database saved")

    def on_lock_button_clicked(self, widget):
        if self.database_manager.made_database_changes() is True:
            self.show_save_dialog()
        else:
            self.lock_database()

    def on_save_dialog_save_button_clicked(self, widget, save_dialog, tab_close, timeout):
        self.database_manager.save_database()
        save_dialog.destroy()
        self.lock_database()

        if timeout is True:
            for db in self.window.opened_databases:
                if db.database_manager.database_path == self.database_manager.database_path:
                    self.window.opened_databases.remove(db)
            self.window.close_tab(self.parent_widget)

        if tab_close is True:
            self.window.close_tab(self.parent_widget)

    def on_save_dialog_discard_button_clicked(self, widget, save_dialog, tab_close, timeout):
        save_dialog.destroy()
        self.lock_database()

        if timeout is True:
            for db in self.window.opened_databases:
                if db.database_manager.database_path == self.database_manager.database_path:
                    self.window.opened_databases.remove(db)
            self.window.close_tab(self.parent_widget)

        if tab_close is True:
            self.window.close_tab(self.parent_widget)

    def on_add_entry_button_clicked(self, widget):
        self.start_database_lock_timer()
        self.database_manager.changes = True
        entry = self.database_manager.add_entry_to_database(None, None, None, None, None, "0", self.database_manager.get_group_uuid_from_group_object(self.current_group))
        self.current_group = entry
        self.pathbar.add_pathbar_button_to_pathbar(self.database_manager.get_entry_uuid_from_entry_object(self.current_group))
        self.show_page_of_new_directory(False, True)

        self.show_database_action_revealer("Added Entry")

    def on_add_group_button_clicked(self, widget):
        self.start_database_lock_timer()
        self.database_manager.changes = True
        group = self.database_manager.add_group_to_database("", "0", "", self.current_group)
        self.current_group = group
        self.pathbar.add_pathbar_button_to_pathbar(self.database_manager.get_group_uuid_from_group_object(self.current_group))
        self.show_page_of_new_directory(True, False)

        self.show_database_action_revealer("Added Group")

    def on_add_property_button_clicked(self, widget):
        self.start_database_lock_timer()
        entry_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.current_group)
        scrolled_page = self.stack.get_child_by_name(entry_uuid)

        for row in scrolled_page.properties_list_box.get_children():
            scrolled_page.properties_list_box.remove(row)

        self.insert_entry_properties_into_listbox(scrolled_page.properties_list_box, True)

    def on_property_value_entry_changed(self, widget, type):
        self.start_database_lock_timer()
        entry_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.current_group)

        scrolled_page = self.stack.get_child_by_name(self.database_manager.get_entry_uuid_from_entry_object(self.current_group))
        scrolled_page.set_made_database_changes(True)

        if type == "name":
            self.database_manager.set_entry_name(entry_uuid, widget.get_text())

            pathbar_button = self.pathbar.get_pathbar_button(self.database_manager.get_entry_uuid_from_entry_object(self.current_group))
            pathbar_button.set_label(widget.get_text())

        elif type == "username":
            self.database_manager.set_entry_username(entry_uuid, widget.get_text())
        elif type == "password":
            self.database_manager.set_entry_password(entry_uuid, widget.get_text())
        elif type == "url":
            self.database_manager.set_entry_url(entry_uuid, widget.get_text())
        elif type == "notes":
            self.database_manager.set_entry_notes(entry_uuid, widget.get_text(widget.get_start_iter(), widget.get_end_iter(), False))

    def on_entry_icon_button_toggled(self, button):
        self.start_database_lock_timer()
        entry_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.current_group)

        old_icon = str(self.database_manager.get_entry_icon_from_entry_uuid(entry_uuid))

        scrolled_page = self.stack.get_child_by_name(self.database_manager.get_entry_uuid_from_entry_object(self.current_group))

        if old_icon != button.get_name():
            if old_icon == "19":
                scrolled_page.mail_icon_button.set_active(False)
            if old_icon == "9":
                scrolled_page.profile_icon_button.set_active(False)
            if old_icon == "1":
                scrolled_page.network_profile_button.set_active(False)
            if old_icon == "0":
                scrolled_page.key_button.set_active(False)
            if old_icon == "30":
                scrolled_page.terminal_icon_button.set_active(False)
            if old_icon == "34":
                scrolled_page.setting_icon_button.set_active(False)
            if old_icon == "48":
                scrolled_page.folder_icon_button.set_active(False)
            if old_icon == "27":
                scrolled_page.harddrive_icon_button.set_active(False)
            if old_icon == "12":
                scrolled_page.wifi_icon_button.set_active(False)
            if old_icon == "23":
                scrolled_page.desktop_icon_button.set_active(False)
            scrolled_page.set_made_database_changes(True)
            self.database_manager.set_entry_icon(entry_uuid, button.get_name())

    def on_entry_color_button_toggled(self, button):
        print("on_entry_color_button_toggled")
        self.start_database_lock_timer()
        entry_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.current_group)

        scrolled_page = self.stack.get_child_by_name(self.database_manager.get_entry_uuid_from_entry_object(self.current_group))

        old_color = self.database_manager.get_entry_color_from_entry_uuid(entry_uuid)

        if old_color != button.get_name():
            if old_color == "NoneColorButton":
                scrolled_page.none_button.set_active(False)
                scrolled_page.none_button.get_children()[0].hide()
            if old_color == "BlueColorButton":
                scrolled_page.blue_button.set_active(False)
                scrolled_page.blue_button.get_children()[0].hide()
            if old_color == "GreenColorButton":
                scrolled_page.green_button.set_active(False)
                scrolled_page.green_button.get_children()[0].hide()
            if old_color == "OrangeColorButton":
                scrolled_page.orange_button.set_active(False)
                scrolled_page.orange_button.get_children()[0].hide()
            if old_color == "RedColorButton":
                scrolled_page.red_button.set_active(False)
                scrolled_page.red_button.get_children()[0].hide()
            if old_color == "PurpleColorButton":
                scrolled_page.purple_button.set_active(False)
                scrolled_page.purple_button.get_children()[0].hide()
            if old_color == "BrownColorButton":
                scrolled_page.brown_button.set_active(False)
                scrolled_page.brown_button.get_children()[0].hide()
            scrolled_page.set_made_database_changes(True)
            self.database_manager.set_entry_color(entry_uuid, button.get_name())

        button.get_children()[0].show_all()

        if button.get_name() != "NoneColorButton":
            image = button.get_children()[0]
            image.set_name("BrightIcon")
        else:
            image = button.get_children()[0]
            image.set_name("DarkIcon")

        if button.get_active() is False:
            button.get_children()[0].hide()

    def on_property_value_group_changed(self, widget, type):
        self.start_database_lock_timer()
        group_uuid = self.database_manager.get_group_uuid_from_group_object(self.current_group)

        scrolled_page = self.stack.get_child_by_name(self.database_manager.get_group_uuid_from_group_object(self.current_group))
        scrolled_page.set_made_database_changes(True)

        if type == "name":
            self.database_manager.set_group_name(group_uuid, widget.get_text())

            for pathbar_button in self.pathbar.get_children():
                if pathbar_button.get_name() == "PathbarButtonDynamic":
                    if pathbar_button.get_uuid() == self.database_manager.get_group_uuid_from_group_object(self.current_group):
                        pathbar_button.set_label(widget.get_text())
        elif type == "notes":
            self.database_manager.set_group_notes(group_uuid, widget.get_text(widget.get_start_iter(), widget.get_end_iter(), False))

    def on_entry_row_button_pressed(self, widget, event):
        self.start_database_lock_timer()
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3 and self.selection_mode is False:
            self.entry_marked_for_delete = self.database_manager.get_entry_object_from_uuid(widget.get_parent().get_entry_uuid())
            entry_context_popover = self.builder.get_object("entry_context_popover")
            entry_context_popover.set_relative_to(widget)
            entry_context_popover.show_all()
            entry_context_popover.popup()

    def on_entry_delete_menu_button_clicked(self, action, param):
        self.start_database_lock_timer()
        entry_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.entry_marked_for_delete)

        # If the deleted entry is in the pathbar, we need to rebuild the pathbar
        if self.pathbar.is_pathbar_button_in_pathbar(entry_uuid) is True:
            self.pathbar.rebuild_pathbar(self.current_group)

        self.database_manager.delete_entry_from_database(self.entry_marked_for_delete)
        self.update_current_stack_page()

    def on_group_row_button_pressed(self, widget, event):
        self.start_database_lock_timer()
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3 and self.selection_mode is False:
            self.group_marked_for_delete = self.database_manager.get_group_object_from_uuid(widget.get_parent().get_group_uuid())
            self.group_marked_for_edit = self.database_manager.get_group_object_from_uuid(widget.get_parent().get_group_uuid())
            group_context_popover = self.builder.get_object("group_context_popover")
            group_context_popover.set_relative_to(widget)
            group_context_popover.show_all()
            group_context_popover.popup()

    def on_group_delete_menu_button_clicked(self, action, param):
        self.start_database_lock_timer()
        group_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.group_marked_for_delete)

        # If the deleted group is in the pathbar, we need to rebuild the pathbar
        if self.pathbar.is_pathbar_button_in_pathbar(group_uuid) is True:
            self.pathbar.rebuild_pathbar(self.current_group)

        self.database_manager.delete_group_from_database(self.group_marked_for_delete)
        self.update_current_stack_page()

    def on_group_edit_menu_button_clicked(self, action, param):
        self.start_database_lock_timer()
        group_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.group_marked_for_edit)

        self.set_current_group(self.group_marked_for_edit)
        self.pathbar.add_pathbar_button_to_pathbar(group_uuid)
        self.show_page_of_new_directory(True, False)

    def on_show_password_button_toggled(self, toggle_button, entry):
        self.start_database_lock_timer()
        if entry.get_visibility() is True:
            entry.set_visibility(False)
        else:
            entry.set_visibility(True)

    def on_copy_secondary_button_clicked(self, widget, position, eventbutton):
        self.start_database_lock_timer()
        if self.clipboard_timer is not NotImplemented:
            self.clipboard_timer.cancel()

        self.clipboard.set_text(widget.get_text(), -1)
        clear_clipboard_time = passwordsafe.config_manager.get_clear_clipboard()
        self.clipboard_timer = Timer(clear_clipboard_time, self.clear_clipboard)
        self.clipboard_timer.start()

    def on_password_entry_copy_clipboard(self, widget, test):
        self.start_database_lock_timer()
        if self.clipboard_timer is not NotImplemented:
            self.clipboard_timer.cancel()

        self.clipboard.set_text(widget.get_text(), -1)
        clear_clipboard_time = passwordsafe.config_manager.get_clear_clipboard()
        self.clipboard_timer = Timer(clear_clipboard_time, self.clear_clipboard)
        self.clipboard_timer.start()

    def on_link_secondary_button_clicked(self, widget, position, eventbutton):
        self.start_database_lock_timer()
        Gtk.show_uri_on_window(self.window, widget.get_text(), Gtk.get_current_event_time())

    def on_popup_generate_password_popover(self, widget, entry):
        self.start_database_lock_timer()
        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/PasswordSafe/entry_page.ui")

        popover = builder.get_object("generate_password_popover")
        digit_spin_button = builder.get_object("digit_spin_button")
        generate_button = builder.get_object("generate_button")

        digit_adjustment = Gtk.Adjustment(16, 5, 50, 1, 5)
        digit_spin_button.set_adjustment(digit_adjustment)

        generate_button.connect("clicked", self.on_generate_button_clicked, builder, entry, digit_spin_button)

        popover.set_relative_to(widget)
        popover.show_all()
        popover.popup()

    def on_generate_button_clicked(self, widget, builder, entry, digit_spin_button):
        self.start_database_lock_timer()
        high_letter_toggle_button = builder.get_object("high_letter_toggle_button")
        low_letter_toggle_button = builder.get_object("low_letter_toggle_button")
        number_toggle_button = builder.get_object("number_toggle_button")
        special_toggle_button = builder.get_object("special_toggle_button")

        digits = digit_spin_button.get_value_as_int()

        password = passwordsafe.password_generator.generate(digits, high_letter_toggle_button.get_active(), low_letter_toggle_button.get_active(), number_toggle_button.get_active(), special_toggle_button.get_active())
        entry.set_text(password)

    def on_database_settings_entry_clicked(self, action, param):
        DatabaseSettingsDialog(self)

    def on_sort_menu_button_entry_clicked(self, action, param, sorting):
        self.start_database_lock_timer()
        passwordsafe.config_manager.set_sort_order(sorting)
        self.list_box_sorting = sorting
        self.rebuild_all_pages()

    def on_headerbar_search_close_button_clicked(self, widget):
        self.start_database_lock_timer()
        self.remove_search_headerbar(None)
        self.show_page_of_new_directory(False, False)

    def on_search_entry_esc_key(self, widget, event, data=None):
        self.start_database_lock_timer()
        if event.keyval == Gdk.KEY_Escape:
            self.remove_search_headerbar(None)
            self.show_page_of_new_directory(False, False)

    def on_headerbar_search_entry_changed(self, widget, search_local_button, search_fulltext_button):
        fulltext = False
        result_list = []

        empty_search_overlay = self.builder.get_object("empty_search_overlay")
        info_search_overlay = self.builder.get_object("info_search_overlay")
        if info_search_overlay in self.search_overlay:
            self.search_overlay.remove(info_search_overlay)

        if empty_search_overlay in self.search_overlay:
            self.search_overlay.remove(empty_search_overlay)

        for row in self.search_list_box.get_children():
            self.search_list_box.remove(row)

        if search_fulltext_button.get_active() is True:
            fulltext = True

        if search_local_button.get_active() is True:
            result_list = self.database_manager.local_search(self.current_group, widget.get_text(), fulltext)
        else:
            result_list = self.database_manager.global_search(widget.get_text(), fulltext)

        if widget.get_text() is not "":
            if empty_search_overlay in self.search_overlay:
                self.search_overlay.remove(empty_search_overlay)

            for uuid in result_list:
                if self.database_manager.check_is_group(uuid):
                    group_row = GroupRow(self, self.database_manager, self.database_manager.get_group_object_from_uuid(uuid))
                    self.search_list_box.add(group_row)
                else:
                    entry_row = EntryRow(self, self.database_manager, self.database_manager.get_entry_object_from_uuid(uuid))
                    self.search_list_box.add(entry_row)

            if len(self.search_list_box.get_children()) is 0:
                self.search_overlay.add_overlay(empty_search_overlay)
        else:
            self.search_overlay.add_overlay(info_search_overlay)

    def on_headerbar_search_entry_enter_pressed(self, widget):
        self.start_database_lock_timer()
        if widget.get_text() is not "":
            uuid = NotImplemented
            first_row = NotImplemented

            if self.search_list_box.get_children()[0].type is "GroupRow":
                uuid = self.search_list_box.get_children()[0].get_group_uuid()
                first_row = self.database_manager.get_group_object_from_uuid(uuid)
            else:
                uuid = self.search_list_box.get_children()[0].get_entry_uuid()
                first_row = self.database_manager.get_entry_object_from_uuid(uuid)

            self.current_group = first_row
            self.pathbar.add_pathbar_button_to_pathbar(uuid)
            self.show_page_of_new_directory(False, False)

    def on_search_filter_button_toggled(self, widget):
        headerbar_search_entry = self.builder.get_object("headerbar_search_entry")
        search_local_button = self.builder.get_object("search_local_button")
        search_fulltext_button = self.builder.get_object("search_fulltext_button")

        self.on_headerbar_search_entry_changed(headerbar_search_entry, search_local_button, search_fulltext_button)

    def on_expiry_control_button_clicked(self, widget):
        self.start_database_lock_timer()
        entry_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.current_group)

        scrolled_page = self.stack.get_child_by_name(self.database_manager.get_entry_uuid_from_entry_object(self.current_group))
        icon_name = scrolled_page.expiry_control_button_image.get_icon_name().icon_name
        icon_size = scrolled_page.expiry_control_button_image.get_icon_name().size

        if icon_name == "list-add-symbolic":
            scrolled_page.expiry_control_button_image.set_from_icon_name("user-trash-symbolic", icon_size)
            scrolled_page.date_button.set_sensitive(True)
            scrolled_page.time_button.set_sensitive(True)
            datetime = self.database_manager.get_entry_expiry_date_from_entry_uuid(entry_uuid)
            scrolled_page.date_label.set_text(str(datetime.date()))
            scrolled_page.time_label.set_text(str(datetime.hour) + ":" + str(datetime.minute))
        else:
            scrolled_page.expiry_control_button_image.set_from_icon_name("list-add-symbolic", icon_size)
            #self.database_manager.set_entry_expiry_date(entry_uuid, None)
            scrolled_page.date_button.set_sensitive(False)
            scrolled_page.time_button.set_sensitive(False)

    def on_expiry_date_changed(self, widget):
        entry_uuid = self.database_manager.get_entry_uuid_from_entry_object(self.current_group)
        scrolled_page = self.stack.get_child_by_name(self.database_manager.get_entry_uuid_from_entry_object(self.current_group))

        calendar = scrolled_page.date_calendar
        minute_button = scrolled_page.minute_spin_button
        hour_button = scrolled_page.hour_spin_button

        self.database_manager.set_entry_expiry_date(entry_uuid, datetime.datetime(calendar.get_date().year, calendar.get_date().month+1, calendar.get_date().day, int(hour_button.get_value()), int(minute_button.get_value())))

        date = self.database_manager.get_entry_expiry_date_from_entry_uuid(entry_uuid)
        scrolled_page.date_label.set_text(str(calendar.get_date().year) + "-" + str(calendar.get_date().month+1) + "-" + str(calendar.get_date().day))
        scrolled_page.time_label.set_text(str(int(hour_button.get_value())) + ":" + str(int(minute_button.get_value())))

    def on_selection_cancel_button_clicked(self, widget):
        self.remove_selection_headerbar()
        self.show_page_of_new_directory(False, False)

    def on_selection_delete_button_clicked(self, widget):
        rebuild_pathbar = False
        reset_stack_page = False
        group = None

        for entry_row in self.entries_selected:
            entry = self.database_manager.get_entry_object_from_uuid(entry_row.get_entry_uuid())
            self.database_manager.delete_entry_from_database(entry)
            # If the deleted entry is in the pathbar, we need to rebuild the pathbar
            if self.pathbar.is_pathbar_button_in_pathbar(entry_row.get_entry_uuid()) is True:
                rebuild_pathbar = True

        for group_row in self.groups_selected:
            group = self.database_manager.get_group_object_from_uuid(group_row.get_group_uuid())
            self.database_manager.delete_group_from_database(group)
            # If the deleted group is in the pathbar, we need to rebuild the pathbar
            if self.pathbar.is_pathbar_button_in_pathbar(group_row.get_group_uuid()) is True:
                rebuild_pathbar = True
            if self.database_manager.get_group_uuid_from_group_object(group) == self.database_manager.get_group_uuid_from_group_object(self.current_group):
                rebuild_pathbar = True
                reset_stack_page = True

        for stack_page in self.stack.get_children():
            if stack_page.check_is_edit_page() is False:
                stack_page.destroy()

        self.show_page_of_new_directory(False, False)

        if rebuild_pathbar is True:
            self.pathbar.rebuild_pathbar(self.current_group)

        if reset_stack_page is True:
            self.current_group = self.database_manager.get_root_group()

        self.show_database_action_revealer("Delete completed")

        self.entries_selected.clear()
        self.groups_selected.clear()
        self.builder.get_object("selection_delete_button").set_sensitive(False)
        self.builder.get_object("selection_cut_button").set_sensitive(False)

        # It is more efficient to do this here and not in the database manager loop
        self.database_manager.changes = True
        if passwordsafe.config_manager.get_save_automatically() is True:
            self.database_manager.save_database()

    def on_selection_cut_button_clicked(self, widget):
        rebuild_pathbar = False

        for entry_row in self.entries_selected:
            entry_uuid = entry_row.get_entry_uuid()
            self.database_manager.move_entry(entry_uuid, self.current_group)
            # If the moved entry is in the pathbar, we need to rebuild the pathbar
            if self.pathbar.is_pathbar_button_in_pathbar(entry_row.get_entry_uuid()) is True:
                rebuild_pathbar = True

        move_conflict = False

        for group_row in self.groups_selected:
            group_uuid = group_row.get_group_uuid()
            if self.database_manager.parent_checker(self.current_group, self.database_manager.get_group_object_from_uuid(group_uuid)) is False:
                self.database_manager.move_group(group_uuid, self.current_group)
            else:
                move_conflict = True
            # If the moved group is in the pathbar, we need to rebuild the pathbar
            if self.pathbar.is_pathbar_button_in_pathbar(group_row.get_group_uuid()) is True:
                rebuild_pathbar = True

        for stack_page in self.stack.get_children():
            if stack_page.check_is_edit_page() is False:
                stack_page.destroy()
        self.show_page_of_new_directory(False, False)

        if rebuild_pathbar is True:
            self.pathbar.rebuild_pathbar(self.current_group)

        if move_conflict is False:
            self.show_database_action_revealer("Move completed")
        else:
            self.show_database_action_revealer("Skipped moving group into itself")

        self.entries_selected.clear()
        self.groups_selected.clear()
        self.builder.get_object("selection_delete_button").set_sensitive(False)
        self.builder.get_object("selection_cut_button").set_sensitive(False)

        # It is more efficient to do this here and not in the database manager loop
        self.database_manager.changes = True
        if passwordsafe.config_manager.get_save_automatically() is True:
            self.database_manager.save_database()

    def on_selection_popover_button_clicked(self, action, param, selection_type):
        scrolled_page = self.stack.get_child_by_name(self.database_manager.get_group_uuid_from_group_object(self.current_group))
        viewport = scrolled_page.get_children()[0]
        overlay = viewport.get_children()[0]
        list_box = overlay.get_children()[0]
        for row in list_box:
            if selection_type is "all":
                row.selection_checkbox.set_active(True)
            else:
                row.selection_checkbox.set_active(False)

    #
    # Dialog Creator
    #

    def show_save_dialog(self, tab_close=None, timeout=None):
        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/PasswordSafe/save_dialog.ui")

        save_dialog = builder.get_object("save_dialog")
        save_dialog.set_destroy_with_parent(True)
        save_dialog.set_modal(True)
        save_dialog.set_transient_for(self.window)

        discard_button = builder.get_object("discard_button")
        save_button = builder.get_object("save_button")

        discard_button.connect("clicked", self.on_save_dialog_discard_button_clicked, save_dialog, tab_close, timeout)
        save_button.connect("clicked", self.on_save_dialog_save_button_clicked, save_dialog, tab_close, timeout)

        save_dialog.present()

    def show_database_action_revealer(self, message):
        database_action_box = self.builder.get_object("database_action_box")

        database_action_label = self.builder.get_object("database_action_label")
        database_action_label.set_text(message)

        database_action_revealer = self.builder.get_object("database_action_revealer")
        database_action_revealer.set_reveal_child(not database_action_revealer.get_reveal_child())
        revealer_timer = Timer(3.0, self.hide_database_action_revealer)
        revealer_timer.start()

    def hide_database_action_revealer(self):
        database_action_revealer = self.builder.get_object("database_action_revealer")
        database_action_revealer.set_reveal_child(not database_action_revealer.get_reveal_child())

    def lock_database(self):
        self.cancel_timers()

        for db in self.window.opened_databases:
            if db.database_manager.database_path == self.database_manager.database_path:
                self.window.opened_databases.remove(db)
        self.window.close_tab(self.parent_widget)

        self.window.start_database_opening_routine(ntpath.basename(self.database_manager.database_path), self.database_manager.database_path)

    def lock_timeout_database(self):
        self.cancel_timers()

        # Workaround against crash (pygobject fault?)
        if self.database_manager.check_is_group(self.database_manager.get_group_uuid_from_group_object(self.current_group)) is False:
            orig_group = self.current_group
            self.current_group = self.database_manager.get_root_group()
            self.show_page_of_new_directory(False, False)

            self.overlay.hide()
            self.unlock_database.unlock_database(timeout=True, unlocked_database=self, original_group=orig_group)
        elif self.stack.get_child_by_name(self.database_manager.get_group_uuid_from_group_object(self.current_group)).edit_page is True:
            orig_group = self.current_group
            self.current_group = self.database_manager.get_root_group()
            self.show_page_of_new_directory(False, False)

            self.overlay.hide()
            self.unlock_database.unlock_database(timeout=True, unlocked_database=self, original_group=orig_group, original_group_edit_page=True)
        else:
            self.overlay.hide()
            self.unlock_database.unlock_database(timeout=True, unlocked_database=self)

        self.send_notification(os.path.splitext(ntpath.basename(self.database_manager.database_path))[0] + " locked", "Keepass safe locked due to inactivity", "dialog-password-symbolic")

    #
    # Helper Methods
    #

    def change_password_entry_visibility(self, entry, toggle_button):
        toggle_button.connect("toggled", self.on_show_password_button_toggled, entry)

        if passwordsafe.config_manager.get_show_password_fields() is False:
            entry.set_visibility(False)
        else:
            toggle_button.toggled()
            entry.set_visibility(True)

    def show_generate_password_popover(self, show_password_button, entry):
        show_password_button.connect("clicked", self.on_popup_generate_password_popover, entry)

    def clear_clipboard(self):
        clear_clipboard_time = passwordsafe.config_manager.get_clear_clipboard()
        if clear_clipboard_time is not 0:
            self.clipboard.clear()

    def start_database_lock_timer(self):
        if self.database_lock_timer is not NotImplemented:
            self.database_lock_timer.cancel()
        timeout = passwordsafe.config_manager.get_database_lock_timeout() * 60
        if timeout is not 0:
            self.database_lock_timer = Timer(timeout, self.lock_timeout_database)
            self.database_lock_timer.start()

    def cancel_timers(self):
        if self.clipboard_timer is not NotImplemented:
            self.clipboard_timer.cancel()

        if self.database_lock_timer is not NotImplemented:
            self.database_lock_timer.cancel()

    def send_notification(self, title, text, icon):
        notify = Notify.Notification.new(title, text, icon)
        notify.show()

