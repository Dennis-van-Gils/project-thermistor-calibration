#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automation to calibrate thermistors in a temperature-regulated bath.

Used devices:

- Keysight 34970A data acquisition/switch unit containing a 20-channel
  multiplexer plug-in module (34901A)
- Picotech PT-104 pt100/1000 temperature logger
- PolyScience PD15R recirculating bath

The Keysight unit is loaded with a 20-channel multiplexer board, hence we simply
call this device a mux. The mux channels are to be populated with the
thermistors you wish to calibrate. All thermistors are to be placed inside the
PolyScience temperature bath. The resistances of each thermistor will be logged.
Additionally, an extra pt100 temperature probe (Picotech PT-104, channel 1)
placed alongside the thermistors will log the bath temperature. The bath
temperature as measured by the PolyScience will also be logged (P1: internal
temperature probe, P2: external temperature probe).
"""
__author__ = "Dennis van Gils"
__authoremail__ = "vangils.dennis@gmail.com"
__url__ = "https://github.com/Dennis-van-Gils/project-thermistor-calibration"
__date__ = "02-04-2024"
__version__ = "1.1.0"
print(__url__)
# pylint: disable=wrong-import-position, missing-function-docstring, bare-except

import sys
import time

# VISA address of the Keysight 3497xA data acquisition/switch unit containing a
# multiplexer plug-in module. Hence, we simply call this device a 'mux'.
# MUX_VISA_ADDRESS = "USB0::0x0957::0x2007::MY49018071::INSTR"
MUX_VISA_ADDRESS = "GPIB0::9::INSTR"

# SCPI commands to be send to the mux to set up the scan cycle
scan_list = "(@101:110)"
MUX_SCPI_COMMANDS = [
    f"rout:open {scan_list:s}",
    f"conf:res 1e6,{scan_list:s}",
    f"sens:res:nplc 1,{scan_list:s}",
    f"rout:scan {scan_list:s}",
]

# Settings for the Picotech PT-104
PT104_IP_ADDRESS = "10.10.100.2"
PT104_PORT = 1234
PT104_ENA_channels = [1, 0, 0, 0]
PT104_gain_channels = [1, 0, 0, 0]

# fmt: off
DAQ_INTERVAL_MS   = 1000  # [ms] Update interval for the mux to perform a scan
CHART_INTERVAL_MS = 1000  # [ms] Update interval for all charts
CHART_CAPACITY    = 1800  # [samples]
# fmt: on

# Global flags
TRY_USING_OPENGL = True

# Show debug info in terminal? Warning: Slow! Do not leave on unintentionally.
DEBUG = False

import pyvisa
import matplotlib.pyplot as plt
import numpy as np

import dvg_pyqt_controls as controls
from dvg_debug_functions import dprint, ANSI
from dvg_pyqt_filelogger import FileLogger
from dvg_pyqtgraph_threadsafe import (
    ThreadSafeCurve,
    HistoryChartCurve,
    LegendSelect,
    PlotManager,
)

from dvg_devices.Keysight_3497xA_protocol_SCPI import Keysight_3497xA
from dvg_devices.Keysight_3497xA_qdev import Keysight_3497xA_qdev, INFINITY_CAP
from dvg_devices.Picotech_PT104_protocol_UDP import Picotech_PT104
from dvg_devices.Picotech_PT104_qdev import Picotech_PT104_qdev
from dvg_devices.PolyScience_PD_bath_protocol_RS232 import PolyScience_PD_bath

from PySide6 import QtCore, QtGui, QtWidgets as QtWid
from PySide6.QtCore import Slot
import pyqtgraph as pg

print(f"PySide6   {QtCore.__version__}")  # type: ignore
print(f"PyQtGraph {pg.__version__}")

if TRY_USING_OPENGL:
    try:
        import OpenGL.GL as gl  # pylint: disable=unused-import
        from OpenGL.version import __version__ as gl_version
    except:  # pylint: disable=bare-except
        print("PyOpenGL  not found")
        print("To install: `conda install pyopengl` or `pip install pyopengl`")
    else:
        print(f"PyOpenGL  {gl_version}")
        pg.setConfigOptions(useOpenGL=True)
        pg.setConfigOptions(antialias=True)
        pg.setConfigOptions(enableExperimental=True)
else:
    print("PyOpenGL  disabled")
print()

# Global pyqtgraph configuration
# pg.setConfigOptions(leftButtonPan=False)
pg.setConfigOption("background", controls.COLOR_GRAPH_BG)
pg.setConfigOption("foreground", controls.COLOR_GRAPH_FG)

# ------------------------------------------------------------------------------
#   MainWindow
# ------------------------------------------------------------------------------


class MainWindow(QtWid.QWidget):
    def __init__(
        self,
        qdev_mux: Keysight_3497xA_qdev,
        qdev_pt104: Picotech_PT104_qdev,
        dev_bath: PolyScience_PD_bath,
        qlog: FileLogger,
        parent=None,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)

        self.qdev_mux = qdev_mux
        self.qdev_pt104 = qdev_pt104
        self.dev_bath = dev_bath
        self.qlog = qlog

        self.setWindowTitle("Calibration thermistors")
        self.setGeometry(20, 60, 1200, 900)
        self.setStyleSheet(
            controls.SS_TEXTBOX_READ_ONLY
            + controls.SS_GROUP
            + controls.SS_HOVER
        )

        self.timer_GUI = QtCore.QTimer()
        self.timer_GUI.timeout.connect(self.update_GUI)

        # -------------------------
        #   Top frame
        # -------------------------

        # Left box
        self.qlbl_recording_time = QtWid.QLabel()
        self.qlbl_recording_time.setStyleSheet("QLabel {min-width: 7em}")

        vbox_left = QtWid.QVBoxLayout()
        vbox_left.addStretch(1)
        vbox_left.addWidget(self.qlbl_recording_time, stretch=0)

        # Middle box
        self.qlbl_title = QtWid.QLabel("Thermistor calibration")
        self.qlbl_title.setFont(
            QtGui.QFont("Palatino", 14, weight=QtGui.QFont.Weight.Bold)
        )
        self.qlbl_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.qlbl_cur_date_time = QtWid.QLabel("00-00-0000    00:00:00")
        self.qlbl_cur_date_time.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.qpbt_record = controls.create_Toggle_button(
            "Click to start recording to file"
        )
        self.qpbt_record.setMinimumWidth(400)
        # fmt: off
        self.qpbt_record.clicked.connect(lambda state: qlog.record(state))  # pylint: disable=unnecessary-lambda
        # fmt: on

        vbox_middle = QtWid.QVBoxLayout()
        vbox_middle.addWidget(self.qlbl_title)
        vbox_middle.addWidget(self.qlbl_cur_date_time)
        vbox_middle.addWidget(self.qpbt_record)

        # Right box
        p = {
            "parent": None,
            "alignment": QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
        }
        self.qpbt_exit = QtWid.QPushButton("Exit")
        self.qpbt_exit.clicked.connect(self.close)
        self.qpbt_exit.setMinimumHeight(30)
        self.qlbl_GitHub = QtWid.QLabel(
            f'<a href="{__url__}">GitHub source</a>', **p
        )
        self.qlbl_GitHub.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.qlbl_GitHub.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.qlbl_GitHub.setOpenExternalLinks(True)

        vbox_right = QtWid.QVBoxLayout()
        vbox_right.setSpacing(4)
        vbox_right.addWidget(self.qpbt_exit, stretch=0)
        vbox_right.addStretch(1)
        vbox_right.addWidget(QtWid.QLabel(__author__, **p))
        vbox_right.addWidget(self.qlbl_GitHub)
        vbox_right.addWidget(QtWid.QLabel(f"v{__version__}", **p))

        # Round up top frame
        hbox_top = QtWid.QHBoxLayout()
        hbox_top.addLayout(vbox_left, stretch=0)
        hbox_top.addStretch(1)
        hbox_top.addLayout(vbox_middle, stretch=0)
        hbox_top.addStretch(1)
        hbox_top.addLayout(vbox_right, stretch=0)

        # ----------------------------------------------------------------------
        #   Chart: Mux readings
        # ----------------------------------------------------------------------

        self.gw_mux = pg.GraphicsLayoutWidget()

        p = {
            "color": controls.COLOR_GRAPH_FG.name(),
            "font-size": "12pt",
            "font-family": "Helvetica",
        }
        self.pi_mux = self.gw_mux.addPlot()
        self.pi_mux.setTitle("Mux resistances", **p)
        self.pi_mux.setLabel("bottom", "history (min)", **p)
        self.pi_mux.setLabel("left", "Ohm", **p)
        self.pi_mux.showGrid(x=1, y=1)
        self.pi_mux.setMenuEnabled(True)
        self.pi_mux.enableAutoRange(axis=pg.ViewBox.XAxis, enable=False)
        self.pi_mux.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        self.pi_mux.setAutoVisible(y=True)

        # ----------------------------------------------------------------------
        #   Create history charts depending on the number of scan channels
        # ----------------------------------------------------------------------

        self.tscurves_mux: list[ThreadSafeCurve] = []

        cm = plt.get_cmap("gist_rainbow")
        for idx, channel in enumerate(
            qdev_mux.dev.state.all_scan_list_channels
        ):
            color = cm(1.0 * idx / qdev_mux.dev.state.N_channels)  # RGBA tuple
            color = np.array(color) * 255
            pen = pg.mkPen(color=color, width=2)

            self.tscurves_mux.append(
                HistoryChartCurve(
                    capacity=CHART_CAPACITY,
                    linked_curve=self.pi_mux.plot(pen=pen, name=channel),
                )
            )

        # ----------------------------------------------------------------------
        #   Legend
        # ----------------------------------------------------------------------

        legend = LegendSelect(linked_curves=self.tscurves_mux)
        legend.grid.setVerticalSpacing(0)

        self.qgrp_legend = QtWid.QGroupBox("Legend")
        self.qgrp_legend.setLayout(legend.grid)

        # ----------------------------------------------------------------------
        #   Chart: Bath temperatures
        # ----------------------------------------------------------------------

        self.gw_bath = pg.GraphicsLayoutWidget()

        p = {
            "color": controls.COLOR_GRAPH_FG.name(),
            "font-size": "12pt",
            "font-family": "Helvetica",
        }
        self.pi_bath = self.gw_bath.addPlot()
        self.pi_bath.setTitle("Bath temperatures", **p)
        self.pi_bath.setLabel("bottom", "history (min)", **p)
        self.pi_bath.setLabel("left", f"{chr(176)}C", **p)
        self.pi_bath.showGrid(x=1, y=1)
        self.pi_bath.setMenuEnabled(True)
        self.pi_bath.enableAutoRange(axis=pg.ViewBox.XAxis, enable=False)
        self.pi_bath.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        self.pi_bath.setAutoVisible(y=True)

        pen1 = pg.mkPen(color=[255, 0, 0], width=3)
        pen2 = pg.mkPen(color=[255, 255, 0], width=3)
        pen3 = pg.mkPen(color=[0, 128, 255], width=3)

        self.tscurve_P1_temp = HistoryChartCurve(
            capacity=CHART_CAPACITY,
            linked_curve=self.pi_bath.plot(pen=pen1, name="P1"),
        )
        self.tscurve_P2_temp = HistoryChartCurve(
            capacity=CHART_CAPACITY,
            linked_curve=self.pi_bath.plot(pen=pen2, name="P2"),
        )
        self.tscurve_pt104_temp = HistoryChartCurve(
            capacity=CHART_CAPACITY,
            linked_curve=self.pi_bath.plot(pen=pen3, name="PT104"),
        )

        self.tscurves_bath = [
            self.tscurve_P1_temp,
            self.tscurve_P2_temp,
            self.tscurve_pt104_temp,
        ]

        # P2 is the external temp probe. Set invisible because we don't use it.
        self.tscurve_P2_temp.curve.setVisible(False)

        # ----------------------------------------------------------------------
        #   PlotManager
        # ----------------------------------------------------------------------

        self.plotitems_all = [self.pi_mux, self.pi_bath]
        self.tscurves_all = self.tscurves_mux + self.tscurves_bath

        self.plot_manager = PlotManager(parent=self)
        self.plot_manager.add_autorange_buttons(linked_plots=self.plotitems_all)
        self.plot_manager.add_preset_buttons(
            linked_plots=self.plotitems_all,
            linked_curves=self.tscurves_all,
            presets=[
                {
                    "button_label": "0:30",
                    "x_axis_label": "history (sec)",
                    "x_axis_divisor": 1,
                    "x_axis_range": (-30, 0),
                },
                {
                    "button_label": "01:00",
                    "x_axis_label": "history (sec)",
                    "x_axis_divisor": 1,
                    "x_axis_range": (-60, 0),
                },
                {
                    "button_label": "03:00",
                    "x_axis_label": "history (min)",
                    "x_axis_divisor": 60,
                    "x_axis_range": (-3, 0),
                },
                {
                    "button_label": "05:00",
                    "x_axis_label": "history (min)",
                    "x_axis_divisor": 60,
                    "x_axis_range": (-5, 0),
                },
                {
                    "button_label": "10:00",
                    "x_axis_label": "history (min)",
                    "x_axis_divisor": 60,
                    "x_axis_range": (-10, 0),
                },
                {
                    "button_label": "30:00",
                    "x_axis_label": "history (min)",
                    "x_axis_divisor": 60,
                    "x_axis_range": (-30, 0),
                },
            ],
        )
        self.plot_manager.add_clear_button(linked_curves=self.tscurves_all)

        qgrp_history = QtWid.QGroupBox("History")
        qgrp_history.setLayout(self.plot_manager.grid)

        # ----------------------------------------------------------------------
        #   Layout: Mux
        # ----------------------------------------------------------------------

        p = {"stretch": 0, "alignment": QtCore.Qt.AlignmentFlag.AlignTop}

        vbox_mux = QtWid.QVBoxLayout()
        vbox_mux.addWidget(self.qgrp_legend, **p)
        vbox_mux.addWidget(qgrp_history, **p)
        vbox_mux.addStretch(1)

        hbox_mux = QtWid.QHBoxLayout()
        hbox_mux.addWidget(qdev_mux.qgrp, **p)
        hbox_mux.addWidget(self.gw_mux, stretch=1)
        hbox_mux.addLayout(vbox_mux)

        # ----------------------------------------------------------------------
        #   Group: PolyScience
        # ----------------------------------------------------------------------

        grpb_bath = QtWid.QGroupBox("PolyScience bath")

        self.qled_P1_temp = QtWid.QLineEdit("nan")
        self.qled_P2_temp = QtWid.QLineEdit("nan")

        grid = QtWid.QGridLayout()
        grid.setVerticalSpacing(4)
        grid.addWidget(QtWid.QLabel("P1 (red)"), 0, 0)
        grid.addWidget(QtWid.QLabel("P2 (yel)"), 1, 0)
        grid.addWidget(self.qled_P1_temp, 0, 1)
        grid.addWidget(self.qled_P2_temp, 1, 1)
        grid.addWidget(QtWid.QLabel(f"{chr(176)}C"), 0, 2)
        grid.addWidget(QtWid.QLabel(f"{chr(176)}C"), 1, 2)

        grpb_bath.setLayout(grid)

        # ----------------------------------------------------------------------
        #   Layout: Bath temperatures
        # ----------------------------------------------------------------------

        vbox_tmp = QtWid.QVBoxLayout()
        vbox_tmp.addWidget(grpb_bath, stretch=0)
        vbox_tmp.addWidget(qdev_pt104.qgrp, stretch=0)
        vbox_tmp.addStretch(1)

        hbox_bath = QtWid.QHBoxLayout()
        hbox_bath.addLayout(vbox_tmp)
        hbox_bath.addWidget(self.gw_bath, stretch=1)

        # ----------------------------------------------------------------------
        #   Round up full window
        # ----------------------------------------------------------------------

        vbox = QtWid.QVBoxLayout(self)
        vbox.addLayout(hbox_top)
        vbox.addLayout(hbox_mux)
        vbox.addLayout(hbox_bath)
        vbox.addStretch(1)

    # --------------------------------------------------------------------------
    #   Handle controls
    # --------------------------------------------------------------------------

    @Slot()
    def update_GUI(self):
        cur_date_time = QtCore.QDateTime.currentDateTime()
        self.qlbl_cur_date_time.setText(
            cur_date_time.toString("dd-MM-yyyy")
            + "    "
            + cur_date_time.toString("HH:mm:ss")
        )
        self.qlbl_recording_time.setText(
            f"REC: {self.qlog.pretty_elapsed()}"
            if self.qlog.is_recording()
            else ""
        )

        for tscurve in self.tscurves_all:
            tscurve.update()

        self.qled_P1_temp.setText(f"{self.dev_bath.state.P1_temp:.2f}")
        self.qled_P2_temp.setText(f"{self.dev_bath.state.P2_temp:.2f}")


# ------------------------------------------------------------------------------
#   Main
# ------------------------------------------------------------------------------

if __name__ == "__main__":

    # Connect to: Keysight 3497xA, aka 'mux'
    # --------------------------------------

    rm = pyvisa.ResourceManager()
    mux = Keysight_3497xA(MUX_VISA_ADDRESS, "MUX")

    if mux.connect(rm):
        mux.begin(MUX_SCPI_COMMANDS)
    else:
        dprint("WARNING: Could not connect to Keysight 3497xA.\n", ANSI.RED)

    # Connect to: Picotech PT-104
    # ---------------------------

    pt104 = Picotech_PT104(name="PT104")
    if pt104.connect(PT104_IP_ADDRESS, PT104_PORT):
        pt104.begin()
        pt104.start_conversion(PT104_ENA_channels, PT104_gain_channels)
    else:
        dprint("WARNING: Could not connect to PicoTech PT-104.\n", ANSI.RED)

    # Connect to: Polyscience bath
    # ----------------------------

    bath = PolyScience_PD_bath()
    if not bath.auto_connect("config/port_PolyScience.txt"):
        dprint("WARNING: Could not connect to PolyScience PD bath.\n", ANSI.RED)

    # Create application
    # ------------------

    QtCore.QThread.currentThread().setObjectName("MAIN")  # For DEBUG info
    app = QtWid.QApplication(sys.argv)

    # Set up multi-threaded communication with devices
    # ------------------------------------------------

    def postprocess_mux_fun():
        """Will be called during an 'worker_DAQ' update, after a mux scan has
        been performed. We use it to parse out the scan readings into separate
        variables and log it to file.
        """

        # DEBUG info
        # It should show that this thread is running inside the 'MUX_DAQ' thread
        # dprint(f"thread: {QtCore.QThread.currentThread().objectName()}")

        if mux_qdev.is_MUX_scanning:
            readings = mux.state.readings
            for idx in range(mux.state.N_channels):
                if readings[idx] > INFINITY_CAP:
                    readings[idx] = np.nan
        else:
            readings = [np.nan] * mux.state.N_channels
            mux.state.readings = readings

        # Add mux readings to charts
        now = time.perf_counter()
        for idx, tscurve in enumerate(window.tscurves_mux):
            tscurve.appendData(now, readings[idx])

        # UGLY HACK: Ideally, querying the Polyscience temperatures should
        # happen inside another dedicated thread. However, we can get away with
        # it by simply running these queries inside the 'MUX_DAQ' thread without
        # issues.
        if bath.is_alive:
            bath.query_P1_temp()
            bath.query_P2_temp()  # External probe

        # Add temperature readings to charts
        window.tscurve_P1_temp.appendData(now, bath.state.P1_temp)
        window.tscurve_P2_temp.appendData(now, bath.state.P2_temp)
        window.tscurve_pt104_temp.appendData(now, pt104.state.ch1_T)

        # Log readings to file
        log.update(mode="w")

    mux_qdev = Keysight_3497xA_qdev(
        dev=mux,
        DAQ_interval_ms=DAQ_INTERVAL_MS,
        DAQ_postprocess_MUX_scan_function=postprocess_mux_fun,
        debug=DEBUG,
    )

    pt104_qdev = Picotech_PT104_qdev(
        dev=pt104,
        DAQ_interval_ms=1000,  # Needs ~720 ms per channel at minimum
        debug=DEBUG,
    )

    # --------------------------------------------------------------------------
    #   File logger
    # --------------------------------------------------------------------------

    def write_header_to_log():
        log.write("time[s]\t")
        log.write("P1_temp[degC]\t")
        log.write("P2_temp[degC]\t")
        log.write(f"PT104_temp[{chr(177)}0.015degC]\t")

        ch_labels = [f"CH{ch}[Ohm]" for ch in mux.state.all_scan_list_channels]
        log.write(f"{chr(9).join(ch_labels)}")  # [TAB]-delimited
        log.write("\n")

    def write_data_to_log():
        log.write(f"{log.elapsed():.1f}\t")
        log.write(f"{bath.state.P1_temp:.2f}\t")
        log.write(f"{bath.state.P2_temp:.2f}\t")
        log.write(f"{pt104.state.ch1_T:.3f}")

        for idx, _ch in enumerate(mux.state.all_scan_list_channels):
            if len(mux.state.readings) <= idx:
                log.write(f"\t{np.nan:.5e}")
            else:
                log.write(f"\t{mux.state.readings[idx]:.5e}")
        log.write("\n")

    log = FileLogger(
        write_header_function=write_header_to_log,
        write_data_function=write_data_to_log,
    )
    log.signal_recording_started.connect(
        lambda filepath: window.qpbt_record.setText(
            f"Recording to file: {filepath}"
        )
    )
    log.signal_recording_stopped.connect(
        lambda: window.qpbt_record.setText("Click to start recording to file")
    )

    # --------------------------------------------------------------------------
    #   Start threads
    # --------------------------------------------------------------------------

    mux_qdev.start()
    pt104_qdev.start()

    # --------------------------------------------------------------------------
    #   Start the main GUI loop
    # --------------------------------------------------------------------------

    @Slot()
    def about_to_quit():
        print("About to quit")
        app.processEvents()
        log.close()
        mux_qdev.quit()
        pt104_qdev.quit()

        try:
            mux.close()
        except:
            pass
        try:
            bath.close()
        except:
            pass
        try:
            pt104.close()
        except:
            pass
        try:
            rm.close()
        except:
            pass

    app.aboutToQuit.connect(about_to_quit)

    window = MainWindow(
        qdev_mux=mux_qdev,
        qdev_pt104=pt104_qdev,
        dev_bath=bath,
        qlog=log,
    )
    window.plot_manager.perform_preset(2)  # Init time axis of the history chart
    window.timer_GUI.start(CHART_INTERVAL_MS)
    window.show()

    sys.exit(app.exec())
