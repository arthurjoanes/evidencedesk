"""Exercise the patched Accelerate loader with tiny CPU-only tensors, offline."""

from __future__ import annotations

import json
import os
import signal
import tempfile
import unittest
from pathlib import Path

import torch
from accelerate import load_checkpoint_in_model
from safetensors.torch import save_file


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.folder = self.root / "checkpoint"
        self.folder.mkdir()
        self.model = torch.nn.Linear(2, 2, bias=False)
        self.weights = torch.ones((2, 2))
        save_file(
            {"weight": self.weights}, self.folder / "shard.safetensors", metadata={"format": "pt"}
        )
        self.index = self.folder / "model.safetensors.index.json"
        # A regression in special-file validation must fail, never hang the suite.
        self.previous_handler = signal.signal(signal.SIGALRM, self.timeout)
        signal.alarm(10)

    @staticmethod
    def timeout(*_):
        raise TimeoutError("Checkpoint validation did not complete in ten seconds")

    def tearDown(self):
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self.previous_handler)
        self.temporary.cleanup()

    def load(self, name):
        self.index.write_text(json.dumps({"weight_map": {"weight": name}}))
        load_checkpoint_in_model(self.model, str(self.folder))

    def test_regular_shard_loads_expected_tensor(self):
        self.load("shard.safetensors")
        self.assertTrue(torch.equal(self.model.weight, self.weights))

    def test_nested_regular_shard_is_supported(self):
        (self.folder / "shards").mkdir()
        (self.folder / "shard.safetensors").rename(self.folder / "shards/part.safetensors")
        self.load("shards/part.safetensors")
        self.assertTrue(torch.equal(self.model.weight, self.weights))

    def test_full_unsharded_checkpoint_is_unchanged(self):
        (self.folder / "shard.safetensors").rename(self.folder / "model.safetensors")
        load_checkpoint_in_model(self.model, str(self.folder))
        self.assertTrue(torch.equal(self.model.weight, self.weights))

    def test_parent_path_is_rejected_before_loading(self):
        (self.folder / "shard.safetensors").rename(self.root / "outside.safetensors")
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.load("../outside.safetensors")

    def test_absolute_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "relative"):
            self.load(str(self.folder / "shard.safetensors"))

    def test_external_symlink_is_rejected(self):
        (self.folder / "shard.safetensors").rename(self.root / "outside.safetensors")
        (self.folder / "linked.safetensors").symlink_to(self.root / "outside.safetensors")
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.load("linked.safetensors")

    def test_internal_symlink_remains_supported(self):
        (self.folder / "linked.safetensors").symlink_to(self.folder / "shard.safetensors")
        self.load("linked.safetensors")
        self.assertTrue(torch.equal(self.model.weight, self.weights))

    def test_fifo_shard_is_rejected_without_opening(self):
        os.mkfifo(self.folder / "pipe.safetensors")
        with self.assertRaisesRegex(ValueError, "regular"):
            self.load("pipe.safetensors")

    def test_directory_shard_is_rejected(self):
        (self.folder / "directory").mkdir()
        with self.assertRaisesRegex(ValueError, "regular"):
            self.load("directory")

    def test_fifo_index_is_rejected_without_opening(self):
        os.mkfifo(self.index)
        with self.assertRaisesRegex(ValueError, "regular"):
            load_checkpoint_in_model(self.model, str(self.folder))

    def test_non_string_shard_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "strings"):
            self.load(["shard.safetensors"])

    def test_missing_shard_is_a_controlled_error(self):
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.load("missing.safetensors")

    def test_oversized_index_is_rejected_before_parsing(self):
        with self.index.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, "16 MiB"):
            load_checkpoint_in_model(self.model, str(self.folder))

    def test_non_object_index_is_rejected(self):
        self.index.write_text("[]")
        with self.assertRaisesRegex(ValueError, "object"):
            load_checkpoint_in_model(self.model, str(self.folder))

    def test_empty_weight_map_is_rejected(self):
        self.index.write_text('{"weight_map": {}}')
        with self.assertRaisesRegex(ValueError, "nonempty"):
            load_checkpoint_in_model(self.model, str(self.folder))


if __name__ == "__main__":
    unittest.main(verbosity=2)
