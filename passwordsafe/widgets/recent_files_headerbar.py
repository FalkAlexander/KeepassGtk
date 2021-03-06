# SPDX-License-Identifier: GPL-3.0-only
from gi.repository import Adw, Gtk


@Gtk.Template(resource_path="/org/gnome/PasswordSafe/gtk/recent_files_headerbar.ui")
class RecentFilesHeaderbar(Adw.Bin):

    __gtype_name__ = "RecentFilesHeaderbar"
