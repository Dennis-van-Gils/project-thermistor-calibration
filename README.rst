.. image:: https://img.shields.io/github/v/release/Dennis-van-Gils/project-thermistor-calibration
    :target: https://github.com/Dennis-van-Gils/project-thermistor-calibration
    :alt: Latest release
.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/psf/black
.. image:: https://img.shields.io/badge/License-MIT-purple.svg
    :target: https://github.com/Dennis-van-Gils/project-thermistor-calibration/blob/master/LICENSE.txt

Thermistor calibration
======================
*A Physics of Fluids project.*

This project concerns automation to calibrate thermistors in a
temperature-regulated bath.

- Github: https://github.com/Dennis-van-Gils/project-thermistor-calibration

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

The PolyScience bath can be manually programmed via its touchscreen to slowly
ramp up the temperature between two set-points. During this temperature ramp you
can run this script to log the thermistor resistance values and the bath
temperatures. The manual of the bath can be found
`here <https://github.com/Dennis-van-Gils/project-thermistor-calibration/blob/main/docs/>`_.

The mux channels that are to be logged must be defined by editing the variables
``scan_list`` and ``MUX_SCPI_COMMANDS`` inside of the
`main.py
<https://github.com/Dennis-van-Gils/project-thermistor-calibration/blob/master/src_python/main.py#L466>`_
file. Background on the SCPI commands can be found in chapter 4 of the Keysight manual
found `here <https://github.com/Dennis-van-Gils/project-thermistor-calibration/blob/main/docs/>`_.

.. image:: https://raw.githubusercontent.com/Dennis-van-Gils/project-thermistor-calibration/master/screenshot.png

Instructions
============
Download the `latest release <https://github.com/Dennis-van-Gils/project-thermistor-calibration/releases/latest>`_
and unpack to a folder onto your drive.

Prerequisites
~~~~~~~~~~~~~

1. VISA library

    The Keysight mux needs an extra software layer to allow for I/O communication,
    namely a VISA library. One should install either
    `NI-VISA <https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html#521671>`_
    or
    `Keysight IO Libraries Suite <https://www.keysight.com/find/iosuiteproductcounter>`_.
    The latter is the smallest and works great.

2. Preferred Python distribution: Anaconda full or Miniconda

    * `Anaconda <https://www.anaconda.com>`_
    * `Miniconda <https://docs.conda.io/en/latest/miniconda.html>`_

Open `Anaconda Prompt` and navigate to the unpacked folder. We are going to
create a dedicated Python environment to install the required packages for
running this script. We name the environment ``therm``. Run the following to
install the necessary packages:

::

   cd src_python
   conda create -n therm python=3.11
   conda activate therm
   pip install -r requirements.txt

Now you can run the graphical user interface.
In Anaconda prompt:

::

   conda activate therm
   ipython main.py