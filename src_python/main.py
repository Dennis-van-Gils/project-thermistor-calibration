#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automation to calibrate thermistors in a temperature-regulated bath.

Used devices:
- Keysight 34970A/34972A data acquisition/switch unit
- Picotech PT-104 pt100/1000 temperature logger
- PolyScience PD15R recirculating baths

The Keysight unit is loaded with a 20-channel multiplexer board (34901A), whose
channels are to be populated with the thermistors you wish to calibrate. All
thermistors are to be placed inside the Polyscience temperature bath. The
resistances of each thermistor will be logged. Additionally, an extra PT100
temperature probe (Picotech PT-104) placed alongside the thermistors will log
the bath temperature. The bath temperature as measured by the Polyscience will
also be logged.
"""
__author__ = "Dennis van Gils"
__authoremail__ = "vangils.dennis@gmail.com"
__url__ = "https://github.com/Dennis-van-Gils/project-thermistor-calibration"
__date__ = "05-02-2024"
__version__ = "1.0.0"

import os
import sys
import time

from PySide6 import QtCore, QtGui, QtWidgets as QtWid
from PySide6.QtCore import Slot

import pyvisa
import matplotlib.pyplot as plt
import numpy as np
import pyqtgraph as pg

import dvg_pyqt_controls as controls
from dvg_pyqt_filelogger import FileLogger
from dvg_pyqtgraph_threadsafe import (
    HistoryChartCurve,
    LegendSelect,
    PlotManager,
)

from dvg_devices.Keysight_3497xA_protocol_SCPI import Keysight_3497xA
from dvg_devices.Keysight_3497xA_qdev import Keysight_3497xA_qdev, INFINITY_CAP
from dvg_devices.Picotech_PT104_protocol_UDP import Picotech_PT104
from dvg_devices.Picotech_PT104_qdev import Picotech_PT104_qdev
from dvg_devices.PolyScience_PD_bath_protocol_RS232 import PolyScience_PD_bath

# Global flags
TRY_USING_OPENGL = True
DEBUG = False  # Show debug info in terminal?

if TRY_USING_OPENGL:
    try:
        import OpenGL.GL as gl  # pylint: disable=unused-import
        from OpenGL.version import __version__ as gl_version
    except:
        print("PyOpenGL  not found")
        print("To install: `conda install pyopengl` or `pip install pyopengl`")
    else:
        print(f"PyOpenGL  {gl_version}")
        pg.setConfigOptions(useOpenGL=True)
        pg.setConfigOptions(antialias=True)
        pg.setConfigOptions(enableExperimental=True)
else:
    print("PyOpenGL  disabled")

# Global pyqtgraph configuration
# pg.setConfigOptions(leftButtonPan=False)
pg.setConfigOption("background", controls.COLOR_GRAPH_BG)
pg.setConfigOption("foreground", controls.COLOR_GRAPH_FG)


def get_current_date_time():
    cur_date_time = QtCore.QDateTime.currentDateTime()
    return (
        cur_date_time.toString("dd-MM-yyyy"),  # Date
        cur_date_time.toString("HH:mm:ss"),  # Time
        cur_date_time.toString("yyMMdd_HHmmss"),  # Reverse notation date-time
    )


# ------------------------------------------------------------------------------
#   MainWindow
# ------------------------------------------------------------------------------


class MainWindow(QtWid.QWidget):
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)

        self.setWindowTitle("Calibration thermistors")
        self.setGeometry(20, 60, 1200, 900)
        self.setStyleSheet(
            controls.SS_TEXTBOX_READ_ONLY
            + controls.SS_GROUP
            + controls.SS_HOVER
        )

        # -------------------------
        #   Top frame
        # -------------------------

        # Left box
        self.qlbl_update_counter = QtWid.QLabel("0")
        self.qlbl_DAQ_rate = QtWid.QLabel("DAQ: nan Hz")
        self.qlbl_DAQ_rate.setStyleSheet("QLabel {min-width: 7em}")
        self.qlbl_recording_time = QtWid.QLabel()

        vbox_left = QtWid.QVBoxLayout()
        vbox_left.addWidget(self.qlbl_update_counter, stretch=0)
        vbox_left.addStretch(1)
        vbox_left.addWidget(self.qlbl_recording_time, stretch=0)
        vbox_left.addWidget(self.qlbl_DAQ_rate, stretch=0)

        # Middle box
        self.qlbl_title = QtWid.QLabel(
            "Thermistor calibration",
            font=QtGui.QFont("Palatino", 14, weight=QtGui.QFont.Weight.Bold),
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
        self.qpbt_record.clicked.connect(lambda state: logger.record(state))

        vbox_middle = QtWid.QVBoxLayout()
        vbox_middle.addWidget(self.qlbl_title)
        vbox_middle.addWidget(self.qlbl_cur_date_time)
        vbox_middle.addWidget(self.qpbt_record)

        # Right box
        p = {
            "alignment": QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        }
        self.qpbt_exit = QtWid.QPushButton("Exit", minimumHeight=30)
        self.qpbt_exit.clicked.connect(self.close)
        self.qlbl_GitHub = QtWid.QLabel(
            f'<a href="{__url__}">GitHub source</a>', **p
        )
        self.qlbl_GitHub.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.qlbl_GitHub.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.qlbl_GitHub.setOpenExternalLinks(True)

        vbox_right = QtWid.QVBoxLayout(spacing=4)
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

        # GraphicsLayoutWidget
        self.gw_mux = pg.GraphicsLayoutWidget()

        p = {
            "color": controls.COLOR_GRAPH_FG.name(),
            "font-size": "12pt",
            "font-family": "Helvetica",
        }
        self.pi_mux = self.gw_mux.addPlot()
        self.pi_mux.setTitle("Mux readings", **p)
        self.pi_mux.setLabel("bottom", "history (min)", **p)
        self.pi_mux.setLabel("left", "resistance (Ohm)", **p)
        self.pi_mux.showGrid(x=1, y=1)
        self.pi_mux.setMenuEnabled(True)
        self.pi_mux.enableAutoRange(axis=pg.ViewBox.XAxis, enable=False)
        self.pi_mux.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        self.pi_mux.setAutoVisible(y=True)

        # Placeholder to be populated depending on the number of scan channels
        self.tscurves_mux = list()  # List of `HistoryChartCurve`

        # ----------------------------------------------------------------------
        #   Legend
        # ----------------------------------------------------------------------

        self.qgrp_legend = QtWid.QGroupBox("Legend")

        # ----------------------------------------------------------------------
        #   PlotManager
        # ----------------------------------------------------------------------

        self.plot_manager = PlotManager(parent=self)
        self.plot_manager.add_autorange_buttons(linked_plots=self.pi_mux)
        self.plot_manager.add_preset_buttons(
            linked_plots=self.pi_mux,
            linked_curves=self.tscurves_mux,
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
        self.plot_manager.add_clear_button(linked_curves=self.tscurves_mux)

        qgrp_history = QtWid.QGroupBox("History")
        qgrp_history.setLayout(self.plot_manager.grid)

        # ----------------------------------------------------------------------
        #   Multiplexer grid
        # ----------------------------------------------------------------------

        vbox_mux = QtWid.QVBoxLayout()
        vbox_mux.addWidget(
            self.qgrp_legend,
            stretch=0,
            alignment=QtCore.Qt.AlignmentFlag.AlignTop,
        )
        vbox_mux.addWidget(
            qgrp_history, stretch=0, alignment=QtCore.Qt.AlignmentFlag.AlignTop
        )
        vbox_mux.addStretch(1)

        hbox_mux = QtWid.QHBoxLayout()
        hbox_mux.addWidget(
            mux_qdev.qgrp, stretch=0, alignment=QtCore.Qt.AlignmentFlag.AlignTop
        )
        hbox_mux.addWidget(self.gw_mux, stretch=1)
        hbox_mux.addLayout(vbox_mux)

        # ----------------------------------------------------------------------
        #   Chart: Bath temperatures
        # ----------------------------------------------------------------------

        # GraphicsLayoutWidget
        self.gw_bath = pg.GraphicsLayoutWidget()

        p = {
            "color": controls.COLOR_GRAPH_FG.name(),
            "font-size": "12pt",
            "font-family": "Helvetica",
        }
        self.pi_bath = self.gw_bath.addPlot()
        self.pi_bath.setTitle("Temperatures")
        self.pi_bath.setLabel("bottom", "history (min)")
        self.pi_bath.setLabel("left", f"({chr(176)}C)")
        self.pi_bath.showGrid(x=1, y=1)
        self.pi_bath.setMenuEnabled(True)
        self.pi_bath.enableAutoRange(axis=pg.ViewBox.XAxis, enable=False)
        self.pi_bath.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        self.pi_bath.setAutoVisible(y=True)

        pen1 = pg.mkPen(color=[255, 0, 0], width=2)
        pen2 = pg.mkPen(color=[255, 255, 0], width=2)
        pen3 = pg.mkPen(color=[0, 128, 255], width=2)
        self.CH_P1_temp = HistoryChartCurve(
            capacity=CH_SAMPLES_MUX, linked_curve=self.pi_bath.plot(pen=pen1)
        )
        self.CH_P2_temp = HistoryChartCurve(
            capacity=CH_SAMPLES_MUX, linked_curve=self.pi_bath.plot(pen=pen2)
        )
        self.CH_PT104_ch1_T = HistoryChartCurve(
            capacity=CH_SAMPLES_MUX, linked_curve=self.pi_bath.plot(pen=pen3)
        )

        # ----------------------------------------------------------------------
        #   Group: Bath temperatures
        # ----------------------------------------------------------------------

        grpb_bath = QtWid.QGroupBox("Polyscience bath")

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
        #   Polyscience and PT104
        # ----------------------------------------------------------------------

        vbox_tmp = QtWid.QVBoxLayout()
        vbox_tmp.addWidget(grpb_bath, stretch=0)
        vbox_tmp.addWidget(pt104_qdev.qgrp, stretch=0)
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

    """"
    @Slot()
    def clear_all_charts(self):
        str_msg = "Are you sure you want to clear all charts?"
        reply = QtWid.QMessageBox.warning(
            self,
            "Clear charts",
            str_msg,
            QtWid.QMessageBox.StandardButton.Yes
            | QtWid.QMessageBox.StandardButton.No,
            QtWid.QMessageBox.StandardButton.No,
        )

        if reply == QtWid.QMessageBox.StandardButton.Yes:
            [CH.clear() for CH in self.CHs_mux]
            self.CH_P1_temp.clear()
            self.CH_P2_temp.clear()
            self.CH_PT104_ch1_T.clear()
    """

    # --------------------------------------------------------------------------
    #   Handle controls
    # --------------------------------------------------------------------------

    @Slot()
    def update_GUI(self):
        str_cur_date, str_cur_time, _ = get_current_date_time()
        self.qlbl_cur_date_time.setText(f"{str_cur_date}    {str_cur_time}")
        self.qlbl_update_counter.setText(f"{mux_qdev.update_counter_DAQ:d}")
        # self.qlbl_DAQ_rate.setText(
        #     f"DAQ: {ard_qdev.obtained_DAQ_rate_Hz:.1f} Hz"
        # )
        self.qlbl_recording_time.setText(
            f"REC: {logger.pretty_elapsed()}" if logger.is_recording() else ""
        )

        # Update curves
        for tscurve in self.tscurves_mux:
            tscurve.update()
        self.CH_P1_temp.update()
        self.CH_P2_temp.update()
        self.CH_P2_temp.curve.setVisible(False)
        self.CH_PT104_ch1_T.update()

        self.qled_P1_temp.setText(f"{bath.state.P1_temp:.2f}")
        self.qled_P2_temp.setText(f"{bath.state.P2_temp:.2f}")


# ------------------------------------------------------------------------------
#   about_to_quit
# ------------------------------------------------------------------------------


@Slot()
def about_to_quit():
    print("About to quit")
    app.processEvents()
    logger.close()
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


# ------------------------------------------------------------------------------
#   DAQ_postprocess_MUX_scan_function
# ------------------------------------------------------------------------------


def DAQ_postprocess_MUX_scan_function():
    """Will be called during an 'worker_DAQ' update, after a mux scan has been
    performed. We use it to parse out the scan readings into separate variables
    and log it to file.
    """

    if mux_qdev.is_MUX_scanning:
        readings = mux.state.readings
        for idx in range(N_channels):
            if readings[idx] > INFINITY_CAP:
                readings[idx] = np.nan
    else:
        readings = [np.nan] * N_channels
        mux.state.readings = readings

    # Add readings to charts
    now = time.perf_counter()
    for idx, tscurve in enumerate(window.tscurves_mux):
        tscurve.appendData(now, readings[idx])

    # TODO: FIX UGLY HACK: put in Polyscience temperature bath and PT104 update
    # here
    # bath.query_P1_temp()
    # bath.query_P2_temp()  # External probe
    window.CH_P1_temp.appendData(now, bath.state.P1_temp)
    window.CH_P2_temp.appendData(now, bath.state.P2_temp)
    window.CH_PT104_ch1_T.appendData(now, pt104.state.ch1_T)

    # Logging to file
    logger.update(mode="w")


# ------------------------------------------------------------------------------
#   File logging
# ------------------------------------------------------------------------------


def write_header_to_log():
    logger.write("time[s]\t")
    logger.write("P1_temp[degC]\t")
    logger.write("P2_temp[degC]\t")
    logger.write("PT104_Ch1[degC]\t")
    for i in range(N_channels - 1):
        logger.write("CH%s[Ohm]\t" % mux.state.all_scan_list_channels[i])
    logger.write("CH%s[Ohm]\n" % mux.state.all_scan_list_channels[-1])


def write_data_to_log():
    logger.write(f"{logger.elapsed():.1f}\t")
    logger.write(f"{bath.state.P1_temp:.2f}\t")
    logger.write(f"{bath.state.P2_temp:.2f}\t")
    logger.write(f"{pt104.state.ch1_T:.3f}")
    for i in range(N_channels):
        if len(mux.state.readings) <= i:
            logger.write("\t%.5e" % np.nan)
        else:
            logger.write("\t%.5e" % mux.state.readings[i])
    logger.write("\n")


# ------------------------------------------------------------------------------
#   Main
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    # A scan will be performed by the mux every N milliseconds
    MUX_SCANNING_INTERVAL_MS = 1000  # [ms]

    # Chart history (CH) buffer sizes in [samples].
    # Multiply this with the corresponding SCANNING_INTERVAL constants to get
    # the history size in time.
    CH_SAMPLES_MUX = 1800

    # The chart will be updated at this interval
    UPDATE_INTERVAL_GUI = 1000  # [ms]

    # --------------------------------------------------------------------------
    #   Set up connection: Keysight 3497xA
    # --------------------------------------------------------------------------

    # VISA address of the Keysight 3497xA data acquisition/switch unit
    # containing a multiplexer plug-in module. Hence, we simply call this device
    # a 'mux'.
    # MUX_VISA_ADDRESS = "USB0::0x0957::0x2007::MY49018071::INSTR"
    MUX_VISA_ADDRESS = "GPIB0::9::INSTR"

    # SCPI commands to be send to the 3497xA to set up the scan cycle
    scan_list = "(@101)"
    MUX_SCPI_COMMANDS = [
        "rout:open %s" % scan_list,
        "conf:res 1e6,%s" % scan_list,
        "sens:res:nplc 1,%s" % scan_list,
        "rout:scan %s" % scan_list,
    ]

    rm = pyvisa.ResourceManager()
    mux = Keysight_3497xA(MUX_VISA_ADDRESS, "MUX")
    if mux.connect(rm):
        mux.begin(MUX_SCPI_COMMANDS)

    # --------------------------------------------------------------------------
    #   Set up connection: Picotech PT-104
    # --------------------------------------------------------------------------

    IP_ADDRESS = "10.10.100.2"
    PORT = 1234
    ENA_channels = [1, 0, 0, 0]
    gain_channels = [1, 0, 0, 0]

    pt104 = Picotech_PT104(name="PT104")
    if pt104.connect(IP_ADDRESS, PORT):
        pt104.begin()
        pt104.start_conversion(ENA_channels, gain_channels)

    # --------------------------------------------------------------------------
    #   Set up connection: Polyscience bath
    # --------------------------------------------------------------------------

    bath = PolyScience_PD_bath()
    if not bath.auto_connect("config/port_PolyScience.txt"):
        # TO DO: Handle device not found
        pass  # For now, simply continue on

    # --------------------------------------------------------------------------
    #   Create application
    # --------------------------------------------------------------------------

    QtCore.QThread.currentThread().setObjectName("MAIN")  # For DEBUG info
    app = QtWid.QApplication(sys.argv)
    app.setFont(QtGui.QFont("Arial", 9))
    app.aboutToQuit.connect(about_to_quit)

    # Set up multi-threaded communication with devices
    mux_qdev = Keysight_3497xA_qdev(
        dev=mux,
        DAQ_interval_ms=MUX_SCANNING_INTERVAL_MS,
        DAQ_postprocess_MUX_scan_function=DAQ_postprocess_MUX_scan_function,
    )
    mux_qdev.set_table_readings_format("%.5e")
    mux_qdev.qgrp.setFixedWidth(420)
    pt104_qdev = Picotech_PT104_qdev(dev=pt104, DAQ_interval_ms=1000)

    window = MainWindow()

    # --------------------------------------------------------------------------
    #   Create history charts depending on the number of scan channels
    # --------------------------------------------------------------------------

    N_channels = len(mux.state.all_scan_list_channels)

    # Create thread-safe `HistoryChartCurve`s, aka `tscurves`
    cm = plt.get_cmap("gist_rainbow")
    for i in range(N_channels):
        color = cm(1.0 * i / N_channels)  # Color will now be an RGBA tuple
        color = np.array(color) * 255
        pen = pg.mkPen(color=color, width=2)

        window.tscurves_mux.append(
            HistoryChartCurve(
                capacity=CH_SAMPLES_MUX,
                linked_curve=window.pi_mux.plot(
                    pen=pen, name=mux.state.all_scan_list_channels[i]
                ),
            )
        )

    legend = LegendSelect(linked_curves=window.tscurves_mux)
    legend.grid.setVerticalSpacing(0)
    window.qgrp_legend.setLayout(legend.grid)

    # --------------------------------------------------------------------------
    #   File logger
    # --------------------------------------------------------------------------

    logger = FileLogger(
        write_header_function=write_header_to_log,
        write_data_function=write_data_to_log,
    )
    logger.signal_recording_started.connect(
        lambda filepath: window.qpbt_record.setText(
            f"Recording to file: {filepath}"
        )
    )
    logger.signal_recording_stopped.connect(
        lambda: window.qpbt_record.setText("Click to start recording to file")
    )

    # --------------------------------------------------------------------------
    #   Start threads
    # --------------------------------------------------------------------------

    mux_qdev.start()
    pt104_qdev.start()

    # --------------------------------------------------------------------------
    #   Set up timers
    # --------------------------------------------------------------------------

    timer_GUI = QtCore.QTimer()
    timer_GUI.timeout.connect(window.update_GUI)
    timer_GUI.start(UPDATE_INTERVAL_GUI)

    # --------------------------------------------------------------------------
    #   Start the main GUI loop
    # --------------------------------------------------------------------------

    window.plot_manager.perform_preset(2)  # Init time axis of the history chart
    window.show()
    sys.exit(app.exec())
