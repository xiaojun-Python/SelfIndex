"""Ensure launchd health handling never terminates a busy service."""

from __future__ import annotations

import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import call, patch

from scripts import macos_launch_agent as agent


class MacosLaunchAgentTests(unittest.TestCase):
    def test_transient_health_failure_does_not_kickstart(self):
        with patch.object(agent, "service_is_healthy", side_effect=[False, True]), \
             patch.object(agent, "run_launchctl", return_value=CompletedProcess([], 0)) as launchctl:
            agent.ensure()
        self.assertEqual(launchctl.call_count, 1)
        self.assertEqual(launchctl.call_args.args[0], "print")

    def test_unhealthy_loaded_job_is_not_force_restarted(self):
        with patch.object(agent, "service_is_healthy", return_value=False), \
             patch.object(agent, "wait_for_health", side_effect=[False, False]), \
             patch.object(agent, "run_launchctl", return_value=CompletedProcess([], 0)) as launchctl:
            with self.assertRaises(SystemExit):
                agent.ensure()
        self.assertEqual(launchctl.call_args_list[-1], call("kickstart", f"{agent.launchd_domain()}/{agent.LABEL}"))
        self.assertFalse(any("-k" in invocation.args for invocation in launchctl.call_args_list))

    def test_unloaded_existing_job_is_bootstrapped(self):
        with patch.object(agent, "AGENT_PATH", Path("/tmp/synthetic-agent.plist")), \
             patch.object(agent, "service_is_healthy", return_value=False), \
             patch.object(agent, "wait_for_health", return_value=True), \
             patch.object(agent, "run_launchctl", side_effect=[
                 CompletedProcess([], 1), CompletedProcess([], 0),
             ]) as launchctl:
            with patch.object(Path, "exists", return_value=True):
                agent.ensure()
        self.assertEqual(launchctl.call_args_list[-1].args[0], "bootstrap")


if __name__ == "__main__":
    unittest.main()
