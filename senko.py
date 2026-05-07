import urequests
import uhashlib


class Senko:
    raw = "https://raw.githubusercontent.com"
    github = "https://github.com"

    def __init__(self, user, repo, url=None, branch="master", working_dir="app", files=["boot.py", "main.py"], headers={}):
        """Senko OTA agent class.

        Args:
            user (str): GitHub user.
            repo (str): GitHub repo to fetch.
            branch (str): GitHub repo branch. (master)
            working_dir (str): Directory inside GitHub repo where the micropython app is.
            url (str): URL to root directory.
            files (list): Files included in OTA update.
            headers (list, optional): Headers for urequests.
        """
        if user:
            self.base_url = "{}/{}/{}".format(self.raw, user, repo)
        elif url:
            self.base_url = url.replace(self.github, self.raw)
        else:
            self.base_url = ""

        self.url = url if url is not None else "{}/{}".format(
            self.base_url, branch)
        if working_dir:
            self.url += "/" + working_dir

        self.headers = headers
        self.files = files

    def _check_hash(self, x, y):
        x_hash = uhashlib.sha1(x.encode())
        y_hash = uhashlib.sha1(y.encode())

        x = x_hash.digest()
        y = y_hash.digest()

        if str(x) == str(y):
            return True
        else:
            return False

    def _get_file(self, url):
        res = None
        try:
            res = urequests.get(url, headers=self.headers)
            if res.status_code == 200:
                content = res.text
                return content
            return None
        except Exception:
            return None
        finally:
            if res:
                res.close()  # Wichtig: Sockets immer schließen!

    def _check_all(self):
        changes = []

        for file in self.files:
            latest_version = self._get_file(
                "{}/{}".format(self.url, file.lstrip("/")))
            if latest_version is None:
                continue

            try:
                with open(file, "r") as local_file:
                    local_version = local_file.read()
            except:
                local_version = ""

            if not self._check_hash(latest_version, local_version):
                changes.append(file)

        return changes

    def fetch(self):
        """Check if newer version is available.

        Returns:
            True - if is, False - if not.
        """
        if not self._check_all():
            return False
        else:
            return True

    def update(self):
        """Replace all changed files with newer one.

        Returns:
            True - if changes were made, False - if not.
        """
        changes = self._check_all()

        for file in changes:
            with open(file, "w") as local_file:
                local_file.write(self._get_file(
                    "{}/{}".format(self.url, file.lstrip("/"))))

        if changes:
            return True
        else:
            return False
