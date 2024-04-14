# File: gui.py
# Created Date: Saturday February 25th 2023
# Author: Steven Atkinson (steven@atkinson.mn)

"""
GUI for training

Usage:
>>> from nam.train.gui import run
>>> run()
"""


# Hack to recover graceful shutdowns in Windows.
# This has to happen ASAP
# See:
# https://github.com/sdatkinson/neural-amp-modeler/issues/105
# https://stackoverflow.com/a/44822794
def _ensure_graceful_shutdowns():
    import os

    if os.name == "nt":  # OS is Windows
        os.environ["FOR_DISABLE_CONSOLE_CTRL_HANDLER"] = "1"


_ensure_graceful_shutdowns()

import re
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path
from tkinter import filedialog
from typing import Callable, Dict, Optional, Sequence

try:  # 3rd-party and 1st-party imports
    import torch

    from nam import __version__
    from nam.train import core
    from nam.models.metadata import GearType, UserMetadata, ToneType

    # Ok private access here--this is technically allowed access
    from nam.train._errors import IncompatibleCheckpointError
    from nam.train._names import INPUT_BASENAMES, LATEST_VERSION

    _install_is_valid = True
    _HAVE_ACCELERATOR = torch.cuda.is_available() or torch.backends.mps.is_available()
except ImportError:
    _install_is_valid = False
    _HAVE_ACCELERATOR = False

if _HAVE_ACCELERATOR:
    _DEFAULT_NUM_EPOCHS = 100
    _DEFAULT_BATCH_SIZE = 16
    _DEFAULT_LR_DECAY = 0.007
else:
    _DEFAULT_NUM_EPOCHS = 20
    _DEFAULT_BATCH_SIZE = 1
    _DEFAULT_LR_DECAY = 0.05
_BUTTON_WIDTH = 20
_BUTTON_HEIGHT = 2
_TEXT_WIDTH = 70

_DEFAULT_DELAY = None
_DEFAULT_IGNORE_CHECKS = False
_DEFAULT_THRESHOLD_ESR = None
_DEFAULT_CHECKPOINT = None

_ADVANCED_OPTIONS_LEFT_WIDTH = 12
_ADVANCED_OPTIONS_RIGHT_WIDTH = 12
_METADATA_RIGHT_WIDTH = 60


@dataclass
class _AdvancedOptions(object):
    """
    :param architecture: Which architecture to use.
    :param num_epochs: How many epochs to train for.
    :param latency: Latency between the input and output audio, in samples.
        None means we don't know and it has to be calibrated.
    :param ignore_checks: Keep going even if a check says that something is wrong.
    :param threshold_esr: Stop training if the ESR gets better than this. If None, don't
        stop.
    :param checkpoint: If provided, try to restart from this checkpoint.
    """

    architecture: core.Architecture
    num_epochs: int
    latency: Optional[int]
    ignore_checks: bool
    threshold_esr: Optional[float]
    checkpoint: Optional[Path]


class _PathType(Enum):
    FILE = "file"
    DIRECTORY = "directory"
    MULTIFILE = "multifile"


class _PathButton(object):
    """
    Button and the path
    """

    def __init__(
        self,
        frame: tk.Frame,
        button_text: str,
        info_str: str,
        path_type: _PathType,
        hooks: Optional[Sequence[Callable[[], None]]] = None,
        color_when_not_set: str = "#EF0000",  # Darker red
        default: Optional[Path] = None,
    ):
        """
        :param hooks: Callables run at the end of setting the value.
        """
        self._button_text = button_text
        self._info_str = info_str
        self._path: Optional[Path] = default
        self._path_type = path_type
        self._frame = frame
        self._widgets = {}
        self._widgets["button"] = tk.Button(
            self._frame,
            text=button_text,
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
            fg="black",
            command=self._set_val,
        )
        self._widgets["button"].pack(side=tk.LEFT)
        self._widgets["label"] = tk.Label(
            self._frame,
            width=_TEXT_WIDTH,
            height=_BUTTON_HEIGHT,
            fg="black",
            bg=None,
            anchor="w",
        )
        self._widgets["label"].pack(side=tk.LEFT)
        self._hooks = hooks
        self._color_when_not_set = color_when_not_set
        self._set_text()

    def __setitem__(self, key, val):
        """
        Implement tk-style setter for state
        """
        if key == "state":
            for widget in self._widgets.values():
                widget["state"] = val
        else:
            raise RuntimeError(
                f"{self.__class__.__name__} instance does not support item assignment for non-state key {key}!"
            )

    @property
    def val(self) -> Optional[Path]:
        return self._path

    def _set_text(self):
        if self._path is None:
            self._widgets["label"]["fg"] = self._color_when_not_set
            self._widgets["label"]["text"] = self._info_str
        else:
            val = self.val
            val = val[0] if isinstance(val, tuple) and len(val) == 1 else val
            self._widgets["label"]["fg"] = "black"
            self._widgets["label"][
                "text"
            ] = f"{self._button_text.capitalize()} set to {val}"

    def _set_val(self):
        res = {
            _PathType.FILE: filedialog.askopenfilename,
            _PathType.DIRECTORY: filedialog.askdirectory,
            _PathType.MULTIFILE: filedialog.askopenfilenames,
        }[self._path_type]()
        if res != "":
            self._path = res
        self._set_text()

        if self._hooks is not None:
            for h in self._hooks:
                h()


class _InputPathButton(_PathButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Download the training file!
        self._widgets["button_download_input"] = tk.Button(
            self._frame,
            text="Download input file",
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
            fg="black",
            command=self._download_input_file,
        )
        self._widgets["button_download_input"].pack(side=tk.RIGHT)

    @classmethod
    def _download_input_file(cls):
        file_urls = {
            "v3_0_0.wav": "https://drive.google.com/file/d/1Pgf8PdE0rKB1TD4TRPKbpNo1ByR3IOm9/view?usp=drive_link",
            "v2_0_0.wav": "https://drive.google.com/file/d/1xnyJP_IZ7NuyDSTJfn-Jmc5lw0IE7nfu/view?usp=drive_link",
            "v1_1_1.wav": "",
            "v1.wav": "",
        }
        # Pick the most recent file.
        for input_basename in INPUT_BASENAMES:
            name = input_basename.name
            url = file_urls.get(name)
            if url:
                if name != LATEST_VERSION.name:
                    print(
                        f"WARNING: File {name} is out of date. "
                        "This needs to be updated!"
                    )
                webbrowser.open(url)
                return


class _ClearablePathButton(_PathButton):
    """
    Can clear a path
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, color_when_not_set="black", **kwargs)
        # Download the training file!
        self._widgets["button_clear"] = tk.Button(
            self._frame,
            text="Clear",
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
            fg="black",
            command=self._clear_path,
        )
        self._widgets["button_clear"].pack(side=tk.RIGHT)

    def _clear_path(self):
        self._path = None
        self._set_text()


class _CheckboxKeys(Enum):
    """
    Keys for checkboxes
    """

    FIT_CAB = "fit_cab"
    SILENT_TRAINING = "silent_training"
    SAVE_PLOT = "save_plot"
    IGNORE_DATA_CHECKS = "ignore_data_checks"


class _BasicModal(object):
    """
    Message and OK button
    """

    def __init__(self, resume_main, msg: str):
        self._root = tk.Toplevel()
        self._text = tk.Label(self._root, text=msg)
        self._text.pack()
        self._ok = tk.Button(
            self._root,
            text="Ok",
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
            fg="black",
            command=self._close,
        )
        self._ok.pack()
        self._resume_main = resume_main

    def _close(self):
        self._root.destroy()
        self._resume_main()


class _GUIWidgets(Enum):
    INPUT_PATH = "input_path"
    OUTPUT_PATH = "output_path"
    TRAINING_DESTINATION = "training_destination"
    METADATA = "metadata"
    ADVANCED_OPTIONS = "advanced_options"
    TRAIN = "train"


class _GUI(object):
    def __init__(self):
        self._root = tk.Tk()
        self._root.title(f"NAM Trainer - v{__version__}")
        self._widgets = {}

        # Buttons for paths:
        self._frame_input = tk.Frame(self._root)
        self._frame_input.pack(anchor="w")
        self._widgets[_GUIWidgets.INPUT_PATH] = _InputPathButton(
            self._frame_input,
            "Input Audio",
            f"Select input (DI) file (e.g. {LATEST_VERSION.name})",
            _PathType.FILE,
            hooks=[self._check_button_states],
        )

        self._frame_output_path = tk.Frame(self._root)
        self._frame_output_path.pack(anchor="w")
        self._widgets[_GUIWidgets.OUTPUT_PATH] = _PathButton(
            self._frame_output_path,
            "Output Audio",
            "Select output (reamped) file - (Choose MULTIPLE FILES to enable BATCH TRAINING)",
            _PathType.MULTIFILE,
            hooks=[self._check_button_states],
        )

        self._frame_train_destination = tk.Frame(self._root)
        self._frame_train_destination.pack(anchor="w")
        self._widgets[_GUIWidgets.TRAINING_DESTINATION] = _PathButton(
            self._frame_train_destination,
            "Train Destination",
            "Select training output directory",
            _PathType.DIRECTORY,
            hooks=[self._check_button_states],
        )

        # Metadata
        self.user_metadata = UserMetadata()
        self._frame_metadata = tk.Frame(self._root)
        self._frame_metadata.pack(anchor="w")
        self._widgets["metadata"] = tk.Button(
            self._frame_metadata,
            text="Metadata...",
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
            fg="black",
            command=self._open_metadata,
        )
        self._widgets["metadata"].pack()
        self.user_metadata_flag = False

        # This should probably be to the right somewhere
        self._get_additional_options_frame()

        # Last frames: avdanced options & train in the SE corner:
        self._frame_advanced_options = tk.Frame(self._root)
        self._frame_train = tk.Frame(self._root)
        # Pack train first so that it's on bottom.
        self._frame_train.pack(side=tk.BOTTOM, anchor="e")
        self._frame_advanced_options.pack(side=tk.BOTTOM, anchor="e")

        # Advanced options for training
        default_architecture = core.Architecture.STANDARD
        self.advanced_options = _AdvancedOptions(
            default_architecture,
            _DEFAULT_NUM_EPOCHS,
            _DEFAULT_DELAY,
            _DEFAULT_IGNORE_CHECKS,
            _DEFAULT_THRESHOLD_ESR,
            _DEFAULT_CHECKPOINT,
        )
        # Window to edit them:

        self._widgets[_GUIWidgets.ADVANCED_OPTIONS] = tk.Button(
            self._frame_advanced_options,
            text="Advanced options...",
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
            fg="black",
            command=self._open_advanced_options,
        )
        self._widgets[_GUIWidgets.ADVANCED_OPTIONS].pack()

        # Train button

        self._widgets[_GUIWidgets.TRAIN] = tk.Button(
            self._frame_train,
            text="Train",
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
            fg="black",
            command=self._train,
        )
        self._widgets[_GUIWidgets.TRAIN].pack()

        self._check_button_states()

    def _check_button_states(self):
        """
        Determine if any buttons should be disabled
        """
        # Train button is disabled unless all paths are set
        if any(
            pb.val is None
            for pb in (
                self._widgets[_GUIWidgets.INPUT_PATH],
                self._widgets[_GUIWidgets.OUTPUT_PATH],
                self._widgets[_GUIWidgets.TRAINING_DESTINATION],
            )
        ):
            self._widgets[_GUIWidgets.TRAIN]["state"] = tk.DISABLED
            return
        self._widgets[_GUIWidgets.TRAIN]["state"] = tk.NORMAL

    def _get_additional_options_frame(self):
        # Checkboxes
        # TODO get these definitions into __init__()
        self._frame_checkboxes = tk.Frame(self._root)
        self._frame_checkboxes.pack(side=tk.LEFT)
        row = 1

        @dataclass
        class Checkbox(object):
            variable: tk.BooleanVar
            check_button: tk.Checkbutton

        def make_checkbox(
            key: _CheckboxKeys, text: str, default_value: bool
        ) -> Checkbox:
            variable = tk.BooleanVar()
            variable.set(default_value)
            check_button = tk.Checkbutton(
                self._frame_checkboxes, text=text, variable=variable
            )
            self._checkboxes[key] = Checkbox(variable, check_button)
            self._widgets[key] = check_button  # For tracking in set-all-widgets ops

        self._checkboxes: Dict[_CheckboxKeys, Checkbox] = dict()
        make_checkbox(_CheckboxKeys.FIT_CAB, "Cab modeling", False)
        make_checkbox(
            _CheckboxKeys.SILENT_TRAINING,
            "Silent run (suggested for batch training)",
            False,
        )
        make_checkbox(_CheckboxKeys.SAVE_PLOT, "Save ESR plot automatically", True)
        make_checkbox(
            _CheckboxKeys.IGNORE_DATA_CHECKS,
            "Ignore data quality checks (DO AT YOUR OWN RISK!)",
            False,
        )

        # Grid them:
        row = 1
        for v in self._checkboxes.values():
            v.check_button.grid(row=row, column=1, sticky="W")
            row += 1

    def mainloop(self):
        self._root.mainloop()

    def _disable(self):
        self._set_all_widget_states_to(tk.DISABLED)

    def _open_advanced_options(self):
        """
        Open window for advanced options
        """

        self._wait_while_func(lambda resume: _AdvancedOptionsGUI(resume, self))

    def _open_metadata(self):
        """
        Open window for metadata
        """

        self._wait_while_func(lambda resume: _UserMetadataGUI(resume, self))

    def _resume(self):
        self._set_all_widget_states_to(tk.NORMAL)
        self._check_button_states()

    def _set_all_widget_states_to(self, state):
        for widget in self._widgets.values():
            widget["state"] = state

    def _train(self):
        # Advanced options:
        num_epochs = self.advanced_options.num_epochs
        architecture = self.advanced_options.architecture
        delay = self.advanced_options.latency
        file_list = self._widgets[_GUIWidgets.OUTPUT_PATH].val
        threshold_esr = self.advanced_options.threshold_esr
        checkpoint = self.advanced_options.checkpoint

        # Advanced-er options
        # If you're poking around looking for these, then maybe it's time to learn to
        # use the command-line scripts ;)
        lr = 0.004
        lr_decay = _DEFAULT_LR_DECAY
        batch_size = _DEFAULT_BATCH_SIZE
        seed = 0

        # Run it
        for file in file_list:
            print("Now training {}".format(file))
            basename = re.sub(r"\.wav$", "", file.split("/")[-1])

            try:
                trained_model = core.train(
                    self._widgets[_GUIWidgets.INPUT_PATH].val,
                    file,
                    self._widgets[_GUIWidgets.TRAINING_DESTINATION].val,
                    epochs=num_epochs,
                    delay=delay,
                    architecture=architecture,
                    batch_size=batch_size,
                    lr=lr,
                    lr_decay=lr_decay,
                    seed=seed,
                    silent=self._checkboxes[
                        _CheckboxKeys.SILENT_TRAINING
                    ].variable.get(),
                    save_plot=self._checkboxes[_CheckboxKeys.SAVE_PLOT].variable.get(),
                    modelname=basename,
                    ignore_checks=self._checkboxes[
                        _CheckboxKeys.IGNORE_DATA_CHECKS
                    ].variable.get(),
                    local=True,
                    fit_cab=self._checkboxes[_CheckboxKeys.FIT_CAB].variable.get(),
                    threshold_esr=threshold_esr,
                    checkpoint=checkpoint,
                )
            except IncompatibleCheckpointError as e:
                trained_model = None
                self._wait_while_func(
                    _BasicModal, "Training failed due to incompatible checkpoint!"
                )

            if trained_model is None:
                print("Model training failed! Skip exporting...")
                continue
            print("Model training complete!")
            print("Exporting...")
            outdir = self._widgets[_GUIWidgets.TRAINING_DESTINATION].val
            print(f"Exporting trained model to {outdir}...")
            trained_model.net.export(
                outdir,
                basename=basename,
                user_metadata=(
                    self.user_metadata if self.user_metadata_flag else UserMetadata()
                ),
            )
            print("Done!")

        # Metadata was only valid for 1 run, so make sure it's not used again unless
        # the user re-visits the window and clicks "ok"
        self.user_metadata_flag = False

    def _wait_while_func(self, func, *args, **kwargs):
        """
        Disable this GUI while something happens.
        That function _needs_ to call the provided self._resume when it's ready to
        release me!
        """
        self._disable()
        func(self._resume, *args, **kwargs)


# some typing functions
def _non_negative_int(val):
    val = int(val)
    if val < 0:
        val = 0
    return val


def _type_or_null(T, val):
    val = val.rstrip()
    if val == "null":
        return val
    return T(val)


_int_or_null = partial(_type_or_null, int)
_float_or_null = partial(_type_or_null, float)


def _type_or_null_inv(val):
    return "null" if val is None else str(val)


def _rstripped_str(val):
    return str(val).rstrip()


class _LabeledOptionMenu(object):
    """
    Label (left) and radio buttons (right)
    """

    def __init__(
        self, frame: tk.Frame, label: str, choices: Enum, default: Optional[Enum] = None
    ):
        """
        :param command: Called to propagate option selection. Is provided with the
            value corresponding to the radio button selected.
        """
        self._frame = frame
        self._choices = choices
        height = _BUTTON_HEIGHT
        bg = None
        fg = "black"
        self._label = tk.Label(
            frame,
            width=_ADVANCED_OPTIONS_LEFT_WIDTH,
            height=height,
            fg=fg,
            bg=bg,
            anchor="w",
            text=label,
        )
        self._label.pack(side=tk.LEFT)

        frame_menu = tk.Frame(frame)
        frame_menu.pack(side=tk.RIGHT)

        self._selected_value = None
        default = (list(choices)[0] if default is None else default).value
        self._menu = tk.OptionMenu(
            frame_menu,
            tk.StringVar(master=frame, value=default, name=label),
            # default,
            *[choice.value for choice in choices],  #  if choice.value!=default],
            command=self._set,
        )
        self._menu.config(width=_ADVANCED_OPTIONS_RIGHT_WIDTH)
        self._menu.pack(side=tk.RIGHT)
        # Initialize
        self._set(default)

    def get(self) -> Enum:
        return self._selected_value

    def _set(self, val: str):
        """
        Set the value selected
        """
        self._selected_value = self._choices(val)


class _LabeledText(object):
    """
    Label (left) and text input (right)
    """

    def __init__(
        self,
        frame: tk.Frame,
        label: str,
        default=None,
        type=None,
        left_width=_ADVANCED_OPTIONS_LEFT_WIDTH,
        right_width=_ADVANCED_OPTIONS_RIGHT_WIDTH,
    ):
        """
        :param command: Called to propagate option selection. Is provided with the
            value corresponding to the radio button selected.
        :param type: If provided, casts value to given type
        """
        self._frame = frame
        label_height = 2
        text_height = 1
        self._label = tk.Label(
            frame,
            width=left_width,
            height=label_height,
            fg="black",
            bg=None,
            anchor="w",
            text=label,
        )
        self._label.pack(side=tk.LEFT)

        self._text = tk.Text(
            frame,
            width=right_width,
            height=text_height,
            fg="black",
            bg=None,
        )
        self._text.pack(side=tk.RIGHT)

        self._type = type

        if default is not None:
            self._text.insert("1.0", str(default))

    def get(self):
        try:
            val = self._text.get("1.0", tk.END)  # Line 1, character zero (wat)
            if self._type is not None:
                val = self._type(val)
            return val
        except tk.TclError:
            return None


class _AdvancedOptionsGUI(object):
    """
    A window to hold advanced options (Architecture and number of epochs)
    """

    def __init__(self, resume_main, parent: _GUI):
        self._resume_main = resume_main
        self._parent = parent
        self._root = tk.Toplevel()
        self._root.title("Advanced Options")

        # Architecture: radio buttons
        self._frame_architecture = tk.Frame(self._root)
        self._frame_architecture.pack()
        self._architecture = _LabeledOptionMenu(
            self._frame_architecture,
            "Architecture",
            core.Architecture,
            default=self._parent.advanced_options.architecture,
        )

        # Number of epochs: text box
        self._frame_epochs = tk.Frame(self._root)
        self._frame_epochs.pack()

        self._epochs = _LabeledText(
            self._frame_epochs,
            "Epochs",
            default=str(self._parent.advanced_options.num_epochs),
            type=_non_negative_int,
        )

        # Delay: text box
        self._frame_latency = tk.Frame(self._root)
        self._frame_latency.pack()

        self._latency = _LabeledText(
            self._frame_latency,
            "Reamp latency",
            default=_type_or_null_inv(self._parent.advanced_options.latency),
            type=_int_or_null,
        )

        # Threshold ESR
        self._frame_threshold_esr = tk.Frame(self._root)
        self._frame_threshold_esr.pack()
        self._threshold_esr = _LabeledText(
            self._frame_threshold_esr,
            "Threshold ESR",
            default=_type_or_null_inv(self._parent.advanced_options.threshold_esr),
            type=_float_or_null,
        )

        # Restart from a checkpoint
        self._frame_checkpoint = tk.Frame(self._root)
        self._frame_checkpoint.pack()
        self._path_button_checkpoint = _ClearablePathButton(
            self._frame_checkpoint,
            "Checkpoint",
            "[Optional] Select a checkpoint (.ckpt file) to restart training from",
            _PathType.FILE,
            default=self._parent.advanced_options.checkpoint,
        )

        # "Ok": apply and destory
        self._frame_ok = tk.Frame(self._root)
        self._frame_ok.pack()
        self._button_ok = tk.Button(
            self._frame_ok,
            text="Ok",
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
            fg="black",
            command=self._apply_and_destroy,
        )
        self._button_ok.pack()

    def _apply_and_destroy(self):
        """
        Set values to parent and destroy this object
        """
        self._parent.advanced_options.architecture = self._architecture.get()
        epochs = self._epochs.get()
        if epochs is not None:
            self._parent.advanced_options.num_epochs = epochs
        latency = self._latency.get()
        # Value None is returned as "null" to disambiguate from non-set.
        if latency is not None:
            self._parent.advanced_options.latency = (
                None if latency == "null" else latency
            )
        threshold_esr = self._threshold_esr.get()
        if threshold_esr is not None:
            self._parent.advanced_options.threshold_esr = (
                None if threshold_esr == "null" else threshold_esr
            )
        checkpoint_path = self._path_button_checkpoint.val
        self._parent.advanced_options.checkpoint = (
            None if checkpoint_path is None else Path(checkpoint_path)
        )
        self._root.destroy()
        self._resume_main()


class _UserMetadataGUI(object):
    # Things that are auto-filled:
    # Model date
    # gain
    def __init__(self, resume_main, parent: _GUI):
        self._resume_main = resume_main
        self._parent = parent
        self._root = tk.Tk()
        self._root.title("Metadata")

        LabeledText = partial(_LabeledText, right_width=_METADATA_RIGHT_WIDTH)

        # Name
        self._frame_name = tk.Frame(self._root)
        self._frame_name.pack()
        self._name = LabeledText(
            self._frame_name,
            "NAM name",
            default=parent.user_metadata.name,
            type=_rstripped_str,
        )
        # Modeled by
        self._frame_modeled_by = tk.Frame(self._root)
        self._frame_modeled_by.pack()
        self._modeled_by = LabeledText(
            self._frame_modeled_by,
            "Modeled by",
            default=parent.user_metadata.modeled_by,
            type=_rstripped_str,
        )
        # Gear make
        self._frame_gear_make = tk.Frame(self._root)
        self._frame_gear_make.pack()
        self._gear_make = LabeledText(
            self._frame_gear_make,
            "Gear make",
            default=parent.user_metadata.gear_make,
            type=_rstripped_str,
        )
        # Gear model
        self._frame_gear_model = tk.Frame(self._root)
        self._frame_gear_model.pack()
        self._gear_model = LabeledText(
            self._frame_gear_model,
            "Gear model",
            default=parent.user_metadata.gear_model,
            type=_rstripped_str,
        )
        # Gear type
        self._frame_gear_type = tk.Frame(self._root)
        self._frame_gear_type.pack()
        self._gear_type = _LabeledOptionMenu(
            self._frame_gear_type,
            "Gear type",
            GearType,
            default=parent.user_metadata.gear_type,
        )
        # Tone type
        self._frame_tone_type = tk.Frame(self._root)
        self._frame_tone_type.pack()
        self._tone_type = _LabeledOptionMenu(
            self._frame_tone_type,
            "Tone type",
            ToneType,
            default=parent.user_metadata.tone_type,
        )

        # "Ok": apply and destory
        self._frame_ok = tk.Frame(self._root)
        self._frame_ok.pack()
        self._button_ok = tk.Button(
            self._frame_ok,
            text="Ok",
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
            fg="black",
            command=self._apply_and_destroy,
        )
        self._button_ok.pack()

    def _apply_and_destroy(self):
        """
        Set values to parent and destroy this object
        """
        self._parent.user_metadata.name = self._name.get()
        self._parent.user_metadata.modeled_by = self._modeled_by.get()
        self._parent.user_metadata.gear_make = self._gear_make.get()
        self._parent.user_metadata.gear_model = self._gear_model.get()
        self._parent.user_metadata.gear_type = self._gear_type.get()
        self._parent.user_metadata.tone_type = self._tone_type.get()
        self._parent.user_metadata_flag = True

        self._root.destroy()
        self._resume_main()


def _install_error():
    window = tk.Tk()
    window.title("ERROR")
    label = tk.Label(
        window,
        width=45,
        height=2,
        text="The NAM training software has not been installed correctly.",
    )
    label.pack()
    button = tk.Button(window, width=10, height=2, text="Quit", command=window.destroy)
    button.pack()
    window.mainloop()


def run():
    if _install_is_valid:
        _gui = _GUI()
        _gui.mainloop()
    else:
        _install_error()


if __name__ == "__main__":
    run()
