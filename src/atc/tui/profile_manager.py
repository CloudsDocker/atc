"""Profile management modals: list, add, clone (sibling), edit, delete, and switch."""

from __future__ import annotations

import re
from typing import Any
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static

from .. import config as cfg
from .modals import Confirm


def _sibling_name(name: str) -> str:
    """Suggest sibling name, e.g. dev06 -> dev01 or prd02 -> prd01."""
    if "06" in name:
        return name.replace("06", "01")
    m = re.search(r"(\d+)$", name)
    if m:
        num = int(m.group(1))
        prefix = name[: m.start(1)]
        return f"{prefix}{num + 1:0{len(m.group(1))}d}"
    return f"{name}-sibling"


def _format_details(ptype: str, options: dict[str, Any]) -> str:
    if ptype == "k8s":
        ctx = options.get("context", "--")
        ns = options.get("namespace", "--")
        svc = options.get("service", "--")
        return f"ctx: {ctx} │ ns: {ns} │ svc: {svc}"
    if ptype == "mwaa":
        env = options.get("environment", "--")
        reg = options.get("region", "--")
        aws = options.get("aws_profile", "--")
        return f"env: {env} │ reg: {reg} │ aws: {aws}"
    return f"type: {ptype}"


class ProfileEditModal(ModalScreen[tuple[bool, str | None]]):
    """Form to add, clone, or edit a profile."""

    DEFAULT_CSS = """
    ProfileEditModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    .profile-edit-box {
        width: 70;
        height: auto;
        max-height: 23;
        border: solid #30363d;
        background: #161b22;
        padding: 1 2;
        color: #c9d1d9;
    }
    .edit-title {
        text-style: bold;
        color: #58a6ff;
        margin-bottom: 1;
    }
    .profile-edit-box Input, .profile-edit-box Select {
        margin-bottom: 0;
    }
    .edit-buttons {
        height: 3;
        align: center middle;
        margin-top: 0;
    }
    .edit-buttons Button {
        margin: 0 1;
    }
    .err-msg {
        color: #f85149;
        min-height: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        mode: str = "add",
        profile: cfg.Profile | None = None,
        is_default: bool = False,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.initial_profile = profile
        self.initial_is_default = is_default

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-box profile-edit-box"):
            if self.mode == "clone":
                title = "Clone Profile (Create Sibling)"
            elif self.mode == "edit":
                title = f"Edit Profile: {self.initial_profile.name if self.initial_profile else ''}"
            else:
                title = "Add Profile"
            yield Label(title, classes="edit-title")

            init_name = ""
            init_type = "k8s"
            init_readonly = False
            opts: dict[str, Any] = {}

            if self.initial_profile:
                opts = dict(self.initial_profile.options)
                init_readonly = self.initial_profile.readonly
                init_type = self.initial_profile.type
                if self.mode == "clone":
                    init_name = _sibling_name(self.initial_profile.name)
                    if "namespace" in opts:
                        opts["namespace"] = _sibling_name(str(opts["namespace"]))
                elif self.mode == "edit":
                    init_name = self.initial_profile.name

            type_options = [("Kubernetes (k8s)", "k8s"), ("AWS MWAA (mwaa)", "mwaa")]
            if init_type not in ("k8s", "mwaa"):
                type_options.append((f"{init_type.title()} ({init_type})", init_type))

            yield Input(value=init_name, placeholder="Profile Name (e.g. mqu-eks-dev-airflow3-dev01)", id="inp-name")
            yield Select(
                type_options,
                value=init_type,
                id="sel-type",
                allow_blank=False,
            )

            # Kubernetes fields
            with Vertical(id="k8s-fields"):
                yield Input(value=str(opts.get("context", "")), placeholder="K8s Context (e.g. mqu-eks-dev)", id="inp-context")
                yield Input(value=str(opts.get("namespace", "")), placeholder="Namespace (e.g. airflow3-dev01)", id="inp-ns")
                yield Input(
                    value=str(opts.get("service", "airflow-api-server-cluster-ip-service")),
                    placeholder="Service Name",
                    id="inp-service",
                )
                yield Input(value=str(opts.get("port", 8080)), placeholder="Port (8080)", id="inp-port")
                yield Input(value=str(opts.get("secret", "airflow-secret")), placeholder="Secret Name", id="inp-secret")

            # MWAA fields
            with Vertical(id="mwaa-fields"):
                yield Input(value=str(opts.get("environment", "")), placeholder="MWAA Environment Name", id="inp-env")
                yield Input(value=str(opts.get("region", "")), placeholder="AWS Region (e.g. ap-southeast-2)", id="inp-region")
                yield Input(value=str(opts.get("aws_profile", "")), placeholder="AWS Profile (e.g. default)", id="inp-aws-profile")
                yield Select(
                    [("auto", "auto"), ("invoke_rest_api", "invoke_rest_api"), ("web_login_token", "web_login_token")],
                    value=str(opts.get("strategy", "auto")),
                    id="sel-strategy",
                    allow_blank=False,
                )

            with Horizontal():
                yield Checkbox("Read-only", value=init_readonly, id="chk-readonly")
                yield Checkbox("Default profile", value=self.initial_is_default, id="chk-default")

            yield Label("", id="edit-error", classes="err-msg")

            with Horizontal(classes="edit-buttons"):
                yield Button("Save", variant="success", id="btn-save")
                yield Button("Cancel", variant="error", id="btn-cancel")

    def on_mount(self) -> None:
        sel = self.query_one("#sel-type", Select)
        self._toggle_fields(sel.value if sel.value != Select.NULL else "k8s")

    @on(Select.Changed, "#sel-type")
    def _type_changed(self, event: Select.Changed) -> None:
        if event.value != Select.NULL:
            self._toggle_fields(str(event.value))

    def _toggle_fields(self, ptype: str) -> None:
        k8s = self.query_one("#k8s-fields", Vertical)
        mwaa = self.query_one("#mwaa-fields", Vertical)
        k8s.display = ptype != "mwaa"
        mwaa.display = ptype == "mwaa"

    def action_cancel(self) -> None:
        self.dismiss((False, None))

    @on(Button.Pressed, "#btn-cancel")
    def _cancel_clicked(self) -> None:
        self.action_cancel()

    def action_save(self) -> None:
        self._save()

    @on(Button.Pressed, "#btn-save")
    def _save_clicked(self) -> None:
        self._save()

    @on(Input.Submitted)
    def _input_submitted(self) -> None:
        self._save()

    def _save(self) -> None:
        name = self.query_one("#inp-name", Input).value.strip()
        err = self.query_one("#edit-error", Label)
        if not name:
            err.update("Profile name cannot be empty.")
            return

        conf = getattr(self.app, "config", None)
        old_name = self.initial_profile.name if (self.mode == "edit" and self.initial_profile) else None
        if conf and name in conf.profiles and name != old_name:
            err.update(f"Profile {name!r} already exists.")
            return

        ptype = str(self.query_one("#sel-type", Select).value)
        readonly = self.query_one("#chk-readonly", Checkbox).value
        is_default = self.query_one("#chk-default", Checkbox).value

        data: dict[str, Any] = {"type": ptype, "readonly": readonly}

        if ptype != "mwaa":
            ctx = self.query_one("#inp-context", Input).value.strip()
            ns = self.query_one("#inp-ns", Input).value.strip()
            svc = self.query_one("#inp-service", Input).value.strip()
            port_val = self.query_one("#inp-port", Input).value.strip()
            secret = self.query_one("#inp-secret", Input).value.strip()

            if ptype == "k8s":
                if not ctx:
                    err.update("Kubernetes context is required.")
                    return
                if not ns:
                    err.update("Namespace is required.")
                    return

            try:
                port = int(port_val) if port_val else 8080
            except ValueError:
                err.update("Port must be a valid integer.")
                return

            if ctx:
                data["context"] = ctx
            if ns:
                data["namespace"] = ns
            data["service"] = svc or "airflow-api-server-cluster-ip-service"
            data["port"] = port
            data["secret"] = secret or "airflow-secret"
        elif ptype == "mwaa":
            env = self.query_one("#inp-env", Input).value.strip()
            reg = self.query_one("#inp-region", Input).value.strip()
            aws_prof = self.query_one("#inp-aws-profile", Input).value.strip()
            strat = str(self.query_one("#sel-strategy", Select).value)

            if not env:
                err.update("MWAA environment name is required.")
                return
            if not reg:
                err.update("AWS region is required.")
                return

            data.update({
                "environment": env,
                "region": reg,
                "aws_profile": aws_prof or "default",
                "strategy": strat or "auto",
            })

        cfg_path = getattr(self.app, "config_path", None)
        try:
            cfg.save_profile(name, data, is_default=is_default, old_name=old_name, path=cfg_path)
        except Exception as e:
            err.update(f"Failed to save: {e}")
            return

        self.dismiss((True, name))


class ProfileManagerModal(ModalScreen[str | None]):
    """Modal dialog allowing users to manage, add, clone, edit, delete, and switch profiles."""

    DEFAULT_CSS = """
    ProfileManagerModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    .profile-mgr-box {
        width: 86;
        height: auto;
        max-height: 85%;
        border: solid #30363d;
        background: #161b22;
        padding: 1 2;
        color: #c9d1d9;
    }
    .profile-title {
        text-style: bold;
        color: #58a6ff;
        margin-bottom: 0;
    }
    .profile-hint {
        color: #8b949e;
        margin-bottom: 1;
    }
    #profile-table {
        height: 10;
        min-height: 5;
        background: #0d1117;
        margin-bottom: 1;
    }
    .mgr-buttons {
        height: 3;
        align: center middle;
    }
    .mgr-buttons Button {
        margin: 0 1;
    }
    .mgr-status {
        color: #8b949e;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("enter", "switch_profile", "switch"),
        Binding("s", "switch_profile", "switch"),
        Binding("a", "add_profile", "add"),
        Binding("c", "clone_profile", "clone"),
        Binding("e", "edit_profile", "edit"),
        Binding("d", "delete_profile", "delete"),
        Binding("asterisk", "set_default", "default"),
        Binding("escape", "dismiss_modal", "close"),
        Binding("q", "dismiss_modal", "close"),
    ]

    def __init__(self, selected_profile: str | None = None) -> None:
        super().__init__()
        self.selected_profile = selected_profile
        self.modified = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box profile-mgr-box"):
            yield Label("Profile Manager", classes="profile-title")
            yield Label(
                "[b]Enter/s[/b]: switch  [b]a[/b]: add  [b]c[/b]: clone (sibling)  [b]e[/b]: edit  [b]d[/b]: delete  [b]*[/b]: default  [b]esc[/b]: close",
                classes="profile-hint",
            )
            yield DataTable(id="profile-table", cursor_type="row", zebra_stripes=False)
            with Horizontal(classes="mgr-buttons"):
                yield Button("Switch", variant="primary", id="btn-switch")
                yield Button("Add", variant="success", id="btn-add")
                yield Button("Clone", variant="default", id="btn-clone")
                yield Button("Edit", variant="default", id="btn-edit")
                yield Button("Delete", variant="error", id="btn-delete")
                yield Button("Set Default", variant="default", id="btn-default")
                yield Button("Close", variant="default", id="btn-close")
            yield Static("", id="mgr-status", classes="mgr-status")

    def on_mount(self) -> None:
        table = self.query_one("#profile-table", DataTable)
        table.add_column("PROFILE", width=30)
        table.add_column("TYPE", width=8)
        table.add_column("DETAILS", width=34)
        table.add_column("ACCESS", width=10)
        self._refresh_table()

    def _refresh_table(self, highlight_name: str | None = None) -> None:
        table = self.query_one("#profile-table", DataTable)
        table.clear()
        conf = getattr(self.app, "config", None)
        if not conf or not conf.profiles:
            self._set_status("No profiles configured.")
            return

        highlight_row = 0
        target = highlight_name or self.selected_profile or getattr(self.app, "profile_name", "")

        for i, (name, p) in enumerate(conf.profiles.items()):
            is_def = conf.default == name
            prefix = "★ " if is_def else "  "
            details = _format_details(p.type, p.options)
            access = "⊘ readonly" if p.readonly else "✓ r/w"
            table.add_row(f"{prefix}{name}", p.type, details, access, key=name)
            if name == target:
                highlight_row = i

        if table.row_count > 0:
            table.move_cursor(row=highlight_row)
            table.focus()

    def _selected_row_name(self) -> str | None:
        table = self.query_one("#profile-table", DataTable)
        if table.row_count == 0:
            return None
        return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)

    def _set_status(self, msg: str) -> None:
        self.query_one("#mgr-status", Static).update(msg)

    @on(DataTable.RowSelected, "#profile-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            self.dismiss(str(event.row_key.value))

    # --- Actions -------------------------------------------------------------
    def action_switch_profile(self) -> None:
        name = self._selected_row_name()
        if name:
            self.dismiss(name)

    @on(Button.Pressed, "#btn-switch")
    def _btn_switch(self) -> None:
        self.action_switch_profile()

    def action_add_profile(self) -> None:
        def on_done(res: tuple[bool, str | None]) -> None:
            saved, name = res
            if saved and name:
                self.modified = True
                self._reload_app_config(active_name=name)
                self._refresh_table(highlight_name=name)
                self._set_status(f"✓ Added profile {name}")

        self.app.push_screen(ProfileEditModal(mode="add"), on_done)

    @on(Button.Pressed, "#btn-add")
    def _btn_add(self) -> None:
        self.action_add_profile()

    def action_clone_profile(self) -> None:
        name = self._selected_row_name()
        if not name:
            return
        conf = getattr(self.app, "config", None)
        prof = conf.profiles.get(name) if conf else None
        if not prof:
            return

        def on_done(res: tuple[bool, str | None]) -> None:
            saved, new_name = res
            if saved and new_name:
                self.modified = True
                self._reload_app_config(active_name=new_name)
                self._refresh_table(highlight_name=new_name)
                self._set_status(f"✓ Cloned sibling profile {new_name}")

        self.app.push_screen(ProfileEditModal(mode="clone", profile=prof), on_done)

    @on(Button.Pressed, "#btn-clone")
    def _btn_clone(self) -> None:
        self.action_clone_profile()

    def action_edit_profile(self) -> None:
        name = self._selected_row_name()
        if not name:
            return
        conf = getattr(self.app, "config", None)
        prof = conf.profiles.get(name) if conf else None
        if not prof:
            return
        is_def = conf.default == name if conf else False

        def on_done(res: tuple[bool, str | None]) -> None:
            saved, new_name = res
            if saved and new_name:
                self.modified = True
                self._reload_app_config(active_name=new_name)
                self._refresh_table(highlight_name=new_name)
                self._set_status(f"✓ Updated profile {new_name}")

        self.app.push_screen(ProfileEditModal(mode="edit", profile=prof, is_default=is_def), on_done)

    @on(Button.Pressed, "#btn-edit")
    def _btn_edit(self) -> None:
        self.action_edit_profile()

    def action_delete_profile(self) -> None:
        name = self._selected_row_name()
        if not name:
            return

        def confirmed(yes: bool) -> None:
            if yes:
                cfg_path = getattr(self.app, "config_path", None)
                try:
                    cfg.delete_profile(name, path=cfg_path)
                    self.modified = True
                    self._reload_app_config()
                    self._refresh_table()
                    self._set_status(f"✓ Deleted profile {name}")
                except Exception as e:
                    self._set_status(f"✗ Failed to delete: {e}")

        self.app.push_screen(Confirm(f"Delete profile {name!r}?", "This removes it from config.toml"), confirmed)

    @on(Button.Pressed, "#btn-delete")
    def _btn_delete(self) -> None:
        self.action_delete_profile()

    def action_set_default(self) -> None:
        name = self._selected_row_name()
        if not name:
            return
        cfg_path = getattr(self.app, "config_path", None)
        try:
            cfg.set_default_profile(name, path=cfg_path)
            self.modified = True
            self._reload_app_config(active_name=name)
            self._refresh_table(highlight_name=name)
            self._set_status(f"✓ Set {name} as default")
        except Exception as e:
            self._set_status(f"✗ Failed to set default: {e}")

    @on(Button.Pressed, "#btn-default")
    def _btn_default(self) -> None:
        self.action_set_default()

    def action_dismiss_modal(self) -> None:
        self.dismiss(self._selected_row_name() if self.modified else None)

    @on(Button.Pressed, "#btn-close")
    def _btn_close(self) -> None:
        self.action_dismiss_modal()

    def _reload_app_config(self, active_name: str | None = None) -> None:
        if hasattr(self.app, "reload_config"):
            self.app.reload_config(new_profile=active_name)
