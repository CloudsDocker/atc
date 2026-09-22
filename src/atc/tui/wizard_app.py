from __future__ import annotations

import sys
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, LoadingIndicator, RadioButton, RadioSet, Select

from ..wizard import get_aws_profiles, get_k8s_contexts, get_k8s_namespaces, get_k8s_services, get_mwaa_environments, verify_aws_session, write_to_config

class ConfigComplete(Screen):
    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="complete-box"):
                yield Label("Configuration Saved Successfully!", id="complete-title")
                yield Label("You can now run `atc` to start.", classes="muted")
                yield Button("Exit", variant="success", id="exit-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "exit-btn":
            self.app.exit(0)


class K8sWizardScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Center():
            with Vertical(id="wizard-box"):
                yield Label("Kubernetes Configuration", id="wizard-title")
                yield Label("Fetching contexts...", id="status", classes="muted")
                yield LoadingIndicator(id="loading")
                yield Select([], prompt="Select Context", id="sel-context", disabled=True)
                yield Select([], prompt="Select Namespace", id="sel-namespace", disabled=True)
                yield Select([], prompt="Select Service", id="sel-service", disabled=True)
                yield Input(placeholder="Profile Name (e.g. dev-k8s)", id="inp-profile", disabled=True)
                with Horizontal(classes="buttons"):
                    yield Button("Cancel", variant="error", id="cancel-btn")
                    yield Button("Save", variant="success", id="save-btn", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self.fetch_contexts()

    @work(thread=True)
    def fetch_contexts(self) -> None:
        contexts = get_k8s_contexts()
        self.app.call_from_thread(self._on_contexts_fetched, contexts)

    def _on_contexts_fetched(self, contexts: list[str]) -> None:
        loading = self.query_one("#loading")
        loading.display = False
        status = self.query_one("#status", Label)
        sel = self.query_one("#sel-context", Select)
        
        if not contexts:
            status.update("No contexts found in kubeconfig.")
            return
            
        status.update("Select a Kubernetes Context:")
        sel.set_options([(c, c) for c in contexts])
        sel.disabled = False

    @on(Select.Changed, "#sel-context")
    def context_selected(self, event: Select.Changed) -> None:
        if event.value:
            self.query_one("#sel-namespace", Select).disabled = True
            self.query_one("#sel-service", Select).disabled = True
            self.query_one("#loading").display = True
            self.query_one("#status", Label).update(f"Fetching namespaces for {event.value}...")
            self.fetch_namespaces(event.value)

    @work(thread=True)
    def fetch_namespaces(self, context: str) -> None:
        namespaces = get_k8s_namespaces(context)
        self.app.call_from_thread(self._on_namespaces_fetched, namespaces)

    def _on_namespaces_fetched(self, namespaces: list[str]) -> None:
        self.query_one("#loading").display = False
        sel = self.query_one("#sel-namespace", Select)
        if namespaces:
            self.query_one("#status", Label).update("Select a namespace:")
            sel.set_options([(n, n) for n in namespaces])
            sel.disabled = False
        else:
            self.query_one("#status", Label).update("No namespaces found.")

    @on(Select.Changed, "#sel-namespace")
    def namespace_selected(self, event: Select.Changed) -> None:
        if event.value:
            context = self.query_one("#sel-context", Select).value
            self.query_one("#sel-service", Select).disabled = True
            self.query_one("#loading").display = True
            self.query_one("#status", Label).update(f"Fetching services for {event.value}...")
            self.fetch_services(context, event.value)

    @work(thread=True)
    def fetch_services(self, context: str, namespace: str) -> None:
        services = get_k8s_services(context, namespace)
        self.app.call_from_thread(self._on_services_fetched, services)

    def _on_services_fetched(self, services: list[str]) -> None:
        self.query_one("#loading").display = False
        sel = self.query_one("#sel-service", Select)
        if services:
            self.query_one("#status", Label).update("Select a service:")
            sel.set_options([(s, s) for s in services])
            sel.disabled = False
        else:
            self.query_one("#status", Label).update("No services found.")

    @on(Select.Changed, "#sel-service")
    def service_selected(self, event: Select.Changed) -> None:
        if event.value:
            context = self.query_one("#sel-context", Select).value
            ns = self.query_one("#sel-namespace", Select).value
            self.query_one("#status", Label).update("Enter profile name:")
            inp = self.query_one("#inp-profile", Input)
            inp.value = f"{context}-{ns}"
            inp.disabled = False
            self.query_one("#save-btn", Button).disabled = False

    @on(Button.Pressed, "#cancel-btn")
    def cancel(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#save-btn")
    def save(self) -> None:
        context = self.query_one("#sel-context", Select).value
        ns = self.query_one("#sel-namespace", Select).value
        svc = self.query_one("#sel-service", Select).value
        name = self.query_one("#inp-profile", Input).value

        config_data = {
            "type": "k8s",
            "context": context,
            "namespace": ns,
            "service": svc,
            "port": 8080,
            "secret": "airflow-secret",
        }
        write_to_config(name, config_data)
        self.app.push_screen(ConfigComplete())


class MwaaWizardScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Center():
            with Vertical(id="wizard-box"):
                yield Label("AWS MWAA Configuration", id="wizard-title")
                yield Label("Fetching AWS profiles...", id="status", classes="muted")
                yield LoadingIndicator(id="loading")
                yield Select([], prompt="Select AWS Profile", id="sel-profile", disabled=True)
                yield Select([], prompt="Select Region", id="sel-region", disabled=True)
                yield Select([], prompt="Select MWAA Environment", id="sel-env", disabled=True)
                yield Input(placeholder="Profile Name (e.g. mwaa-dev)", id="inp-profile", disabled=True)
                with Horizontal(classes="buttons"):
                    yield Button("Cancel", variant="error", id="cancel-btn")
                    yield Button("Retry Auth", variant="warning", id="retry-btn", disabled=True)
                    yield Button("Save", variant="success", id="save-btn", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self.fetch_profiles()

    @work(thread=True)
    def fetch_profiles(self) -> None:
        profiles = get_aws_profiles()
        self.app.call_from_thread(self._on_profiles_fetched, profiles)

    def _on_profiles_fetched(self, profiles: list[str]) -> None:
        self.query_one("#loading").display = False
        status = self.query_one("#status", Label)
        sel = self.query_one("#sel-profile", Select)
        
        if not profiles:
            status.update("No AWS profiles found in ~/.aws/credentials.")
            return
            
        status.update("Select an AWS Profile:")
        sel.set_options([(p, p) for p in profiles])
        sel.disabled = False

    @on(Select.Changed, "#sel-profile")
    def profile_selected(self, event: Select.Changed) -> None:
        if event.value:
            self.query_one("#sel-region", Select).disabled = True
            self.query_one("#sel-env", Select).disabled = True
            self.query_one("#loading").display = True
            self.query_one("#status", Label).update(f"Verifying session for {event.value}...")
            self.query_one("#retry-btn", Button).disabled = True
            self.verify_session(event.value)

    @on(Button.Pressed, "#retry-btn")
    def retry_auth(self) -> None:
        profile = self.query_one("#sel-profile", Select).value
        if profile:
            self.query_one("#loading").display = True
            self.query_one("#status", Label).update(f"Retrying session for {profile}...")
            self.query_one("#retry-btn", Button).disabled = True
            self.verify_session(profile)

    @work(thread=True)
    def verify_session(self, profile: str) -> None:
        ok = verify_aws_session(profile)
        self.app.call_from_thread(self._on_session_verified, ok)

    def _on_session_verified(self, ok: bool) -> None:
        self.query_one("#loading").display = False
        if not ok:
            profile = self.query_one("#sel-profile", Select).value
            self.query_one("#status", Label).update(f"AWS session invalid for {profile}.\nPlease run your login command in another terminal.")
            self.query_one("#retry-btn", Button).disabled = False
            return
            
        common_regions = ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "eu-west-1", "eu-central-1", "ap-southeast-1", "ap-southeast-2"]
        sel = self.query_one("#sel-region", Select)
        sel.set_options([(r, r) for r in common_regions])
        sel.disabled = False
        self.query_one("#status", Label).update("Select AWS Region:")

    @on(Select.Changed, "#sel-region")
    def region_selected(self, event: Select.Changed) -> None:
        if event.value:
            profile = self.query_one("#sel-profile", Select).value
            self.query_one("#loading").display = True
            self.query_one("#status", Label).update(f"Fetching MWAA environments in {event.value}...")
            self.fetch_envs(profile, event.value)

    @work(thread=True)
    def fetch_envs(self, profile: str, region: str) -> None:
        envs = get_mwaa_environments(profile, region)
        self.app.call_from_thread(self._on_envs_fetched, envs)

    def _on_envs_fetched(self, envs: list[str]) -> None:
        self.query_one("#loading").display = False
        sel = self.query_one("#sel-env", Select)
        if envs:
            self.query_one("#status", Label).update("Select MWAA Environment:")
            sel.set_options([(e, e) for e in envs])
            sel.disabled = False
        else:
            self.query_one("#status", Label).update("No environments found.")

    @on(Select.Changed, "#sel-env")
    def env_selected(self, event: Select.Changed) -> None:
        if event.value:
            self.query_one("#status", Label).update("Enter profile name:")
            inp = self.query_one("#inp-profile", Input)
            inp.value = event.value
            inp.disabled = False
            self.query_one("#save-btn", Button).disabled = False

    @on(Button.Pressed, "#cancel-btn")
    def cancel(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#save-btn")
    def save(self) -> None:
        profile = self.query_one("#sel-profile", Select).value
        region = self.query_one("#sel-region", Select).value
        env = self.query_one("#sel-env", Select).value
        name = self.query_one("#inp-profile", Input).value

        config_data = {
            "type": "mwaa",
            "environment": env,
            "region": region,
            "aws_profile": profile,
            "strategy": "auto"
        }
        write_to_config(name, config_data)
        self.app.push_screen(ConfigComplete())


class MenuScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Center():
            with Vertical(id="menu-box"):
                yield Label("Welcome to the ATC Wizard", id="wizard-title")
                yield Label("What environment do you want to configure?", classes="muted")
                yield RadioSet(
                    RadioButton("Kubernetes (K8s)", id="k8s"),
                    RadioButton("AWS MWAA", id="mwaa"),
                    id="type-select"
                )
                with Horizontal(classes="buttons"):
                    yield Button("Exit", variant="error", id="exit-btn")
                    yield Button("Continue", variant="primary", id="continue-btn")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "exit-btn":
            self.app.exit(0)
        elif event.button.id == "continue-btn":
            rs = self.query_one("#type-select", RadioSet)
            if rs.pressed_button:
                if rs.pressed_button.id == "k8s":
                    self.app.push_screen(K8sWizardScreen())
                elif rs.pressed_button.id == "mwaa":
                    self.app.push_screen(MwaaWizardScreen())


class WizardApp(App):
    CSS = """
    Screen {
        background: $surface;
        align: center middle;
    }
    
    #menu-box, #wizard-box, #complete-box {
        width: 60;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $panel;
        align: center top;
    }
    
    #wizard-title, #complete-title {
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    
    .muted {
        color: $text-muted;
        margin-bottom: 1;
    }
    
    RadioSet {
        margin-bottom: 2;
    }
    
    Select, Input {
        margin-bottom: 1;
    }
    
    .buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    
    Button {
        margin: 0 1;
    }
    
    LoadingIndicator {
        height: 3;
        margin-bottom: 1;
        display: none;
    }
    """
    
    BINDINGS = [
        ("q", "quit", "Quit Wizard"),
    ]

    def on_mount(self) -> None:
        self.push_screen(MenuScreen())
