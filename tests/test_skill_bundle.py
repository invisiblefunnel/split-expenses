"""Check the release archive against what a skills upload actually accepts.

The zip is the only form of this skill most people will ever install, and it is
validated by an upload dialog rather than by anything here: Settings > Skills in
the Claude app, and the skills upload in ChatGPT, which checks frontmatter
against the Agent Skills specification. Either accepts the bundle or it doesn't,
somewhere nobody is watching a log.

So these build the artifact the way the release does, by reading the git archive
invocation out of .github/workflows/release.yml rather than restating it, and
hold the result to the union of both platforms' published rules. The workflow
stays the one description of what ships; a pathspec added there and nowhere else
still lands under test.
"""

import re
import shlex
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _release_archive_argv():
    """The Release workflow's git archive invocation, as an argument list."""

    text = WORKFLOW.read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()]
    starts = [n for n, line in enumerate(lines) if line.startswith("git archive")]
    if len(starts) != 1:
        raise AssertionError(f"expected one git archive command in {WORKFLOW.name}")

    # The command is written across several lines of a YAML block scalar, which
    # keeps the shell's backslash continuations intact for us to rejoin.
    command = []
    for line in lines[starts[0] :]:
        command.append(line.rstrip("\\"))
        if not line.endswith("\\"):
            break

    return shlex.split(" ".join(command))


ARCHIVE = _release_archive_argv()


def _argument(start):
    """The archive argument beginning with `start`.

    Each one the tests read carries something a release depends on, so a
    workflow that stopped passing it should say which one it dropped rather
    than surface here as a parse failure.
    """

    for argument in ARCHIVE:
        if argument.startswith(start):
            return argument
    raise AssertionError(f"the release's git archive command passes no {start}")


# --prefix is the archive's single top-level folder, and a skill has to ship in
# a folder carrying its own name.
PREFIX = _argument("--prefix=").split("=", 1)[1]

# Where the built archive is written, so that a test run can redirect it.
OUTPUT = ARCHIVE.index(_argument("-o")) + 1

# The tree the trailing pathspecs resolve against, and then those pathspecs:
# the allowlist of files a release ships.
TREE = _argument("$GITHUB_REF_NAME:")
SKILL_DIR = TREE.split(":", 1)[1]
BUNDLED = ARCHIVE[ARCHIVE.index(TREE) + 1 :]

# Frontmatter fields the Agent Skills specification defines. Anything else is a
# validation error rather than a key a reader passes over.
SPEC_FIELDS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)

MAX_NAME = 64
MAX_DESCRIPTION = 1024

# Claude rejects a skill name containing either word. The specification says
# nothing about them, so a name can clear its reference validator and still be
# refused on upload.
RESERVED = ("anthropic", "claude")

# A path the instructions hand to the agent to read or run, like
# "scripts/settle.py": at least one directory segment, then a file with an
# extension. Anchored on the slash so prose is not read as a filename, and
# applied with links stripped so a URL's path is not read as one either.
LINK = re.compile(r"\bhttps?://\S+")
REFERENCE = re.compile(r"(?<![\w/.])[\w-]+(?:/[\w-]+)*/[\w-]+\.\w+")


def _parse_frontmatter(text):
    """The manifest's top-level frontmatter fields.

    The specification's reference validator parses these with strictyaml. This
    suite runs on six interpreters with nothing installed, so this reads the
    flat `key: value` lines the fields are written as, leaving an indented value
    to the key it belongs to.
    """

    if not text.startswith("---"):
        raise AssertionError("SKILL.md must open with YAML frontmatter")

    parts = text.split("---", 2)
    if len(parts) < 3:
        raise AssertionError("SKILL.md frontmatter is never closed with ---")

    fields = {}
    for line in parts[1].splitlines():
        if not line.strip() or line.startswith("#") or line[:1].isspace():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise AssertionError(f"frontmatter line is not a field: {line!r}")
        fields[key.strip()] = value.strip().strip("\"'")

    return fields


class SkillBundleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        output = Path(directory.name) / "split-expenses.zip"

        # The tag a release builds from is this checkout, and -o is redirected
        # so that running the suite does not write into the repository.
        argv = [arg.replace("$GITHUB_REF_NAME", "HEAD") for arg in ARCHIVE]
        argv[OUTPUT] = str(output)
        subprocess.run(argv, cwd=ROOT, check=True)

        with zipfile.ZipFile(output) as archive:
            cls.entries = archive.namelist()
            # git archive writes directory entries too; an upload reads the
            # files under them.
            cls.files = [e.filename for e in archive.infolist() if not e.is_dir()]
            cls.manifests = [
                name
                for name in cls.files
                if name.rsplit("/", 1)[-1].lower() == "skill.md"
            ]
            cls.manifest = (
                archive.read(cls.manifests[0]).decode("utf-8")
                if len(cls.manifests) == 1
                else None
            )

    def instructions(self):
        """The bundled SKILL.md, or a failure if the archive holds anything but
        the one manifest an upload reads: none at all, or several."""

        self.assertIsNotNone(self.manifest, "the archive holds no single SKILL.md")
        return self.manifest

    def frontmatter(self):
        return _parse_frontmatter(self.instructions())

    def test_one_top_level_folder(self):
        """SKILL.md loose at the root, or two folders side by side, is the
        documented way for an upload to fail."""

        self.assertEqual(
            {name.split("/", 1)[0] for name in self.entries}, {PREFIX[:-1]}
        )

    def test_exactly_one_manifest_at_the_bundle_root(self):
        """A second SKILL.md anywhere in the bundle is rejected, and one nested
        a level down leaves the folder with no manifest at all."""

        self.assertEqual(self.manifests, [f"{PREFIX}SKILL.md"])

    def test_the_archive_holds_the_files_the_workflow_names(self):
        """A pathspec naming a directory rather than a file would quietly widen
        the release; git archive only fails outright on one matching nothing."""

        self.assertEqual(self.files, [f"{PREFIX}{path}" for path in BUNDLED])

    def test_frontmatter_uses_only_specification_fields(self):
        fields = self.frontmatter()

        self.assertEqual(set(fields) - SPEC_FIELDS, set())
        self.assertIn("name", fields)
        self.assertIn("description", fields)

    def test_name_matches_the_folder_and_clears_both_validators(self):
        """The specification requires the name to match the directory it ships
        in, in lowercase alphanumerics and single interior hyphens. Claude adds
        its two reserved words, and rejects XML tags the pattern already
        excludes."""

        name = self.frontmatter()["name"]

        self.assertEqual(name, PREFIX[:-1])
        self.assertRegex(name, r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(name), MAX_NAME)
        for word in RESERVED:
            self.assertNotIn(word, name)

    def test_description_is_present_and_within_the_limit(self):
        """Every installed skill's description sits in the system prompt from
        startup, so it is capped rather than truncated."""

        description = self.frontmatter()["description"]

        self.assertTrue(description)
        self.assertLessEqual(len(description), MAX_DESCRIPTION)
        self.assertNotRegex(description, r"[<>]")

    def test_every_file_the_instructions_name_is_bundled(self):
        """Instructions pointing at a script the release left behind fail where
        it is least visible: after the upload worked, mid-conversation."""

        referenced = sorted(set(REFERENCE.findall(LINK.sub("", self.instructions()))))

        self.assertTrue(referenced, "SKILL.md names no bundled file")
        for path in referenced:
            self.assertIn(f"{PREFIX}{path}", self.files)

    def test_nothing_committed_to_the_skill_is_left_out(self):
        """The other half: the pathspecs are an allowlist, so a file ships only
        once it is named there. A file committed under the skill but missing
        from the workflow would reach nobody."""

        listed = subprocess.run(
            ["git", "ls-files", "--", SKILL_DIR],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        tracked = sorted(
            name.removeprefix(f"{SKILL_DIR}/") for name in listed.stdout.split()
        )

        self.assertEqual(tracked, sorted(BUNDLED))


if __name__ == "__main__":
    unittest.main()
