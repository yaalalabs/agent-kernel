from pathlib import Path


class ResultsLayout:
    """Every path under results/. Returns paths only; folders are created by whoever writes into them."""

    def __init__(self, root: Path, run_id: str):
        self.root = Path(root)
        self.run_id = run_id

    def run_dir(self) -> Path:
        return self.root / self.run_id

    def run_log(self) -> Path:
        return self.run_dir() / "run.log"

    def deployment_dir(self, platform: str, host: str, mode: str, message_type: str) -> Path:
        """Holds state.json, run-metadata.json and cost.csv."""
        return self.run_dir() / platform / host / mode / message_type

    def test_type_dir(self, platform: str, host: str, mode: str, message_type: str, test_type: str) -> Path:
        """Holds summary.csv and graphs/."""
        return self.deployment_dir(platform, host, mode, message_type) / test_type

    def step_dir(self, platform: str, host: str, mode: str, message_type: str, test_type: str, step: int, load_steps: list[int]) -> Path:
        """step-<N>, zero-padded to the digits of the largest saved load step ([1, 10, 100, 1000] -> step-0001)."""
        width = len(str(max(load_steps)))
        return self.test_type_dir(platform, host, mode, message_type, test_type) / f"step-{step:0{width}d}"
