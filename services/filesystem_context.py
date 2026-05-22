class FilesystemContext:
    def __init__(
        self,
        *,
        app_dir,
        os_module,
        re_module,
        html_escape,
        data_path,
        atomic_write_json,
        load_json_file,
    ):
        self.app_dir = app_dir
        self.os = os_module
        self.re = re_module
        self.html_escape = html_escape
        self.data_path = data_path
        self.atomic_write_json = atomic_write_json
        self.load_json_file = load_json_file

    @property
    def relpath(self):
        return self.os.path.relpath

    @property
    def basename(self):
        return self.os.path.basename

    @property
    def join_path(self):
        return self.os.path.join

    @property
    def path_exists(self):
        return self.os.path.exists

    @property
    def path_getmtime(self):
        return self.os.path.getmtime

    @property
    def re_search(self):
        return self.re.search


def filesystem_context(**kwargs):
    return FilesystemContext(**kwargs)
