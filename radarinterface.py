import sys
import random
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtWidgets
import time

import pickle
from datetime import datetime
import queue
import pika
import threading
import signal
import json
import argparse


parser = argparse.ArgumentParser()
parser.add_argument("--port", nargs="+", type=str, default="")
args = parser.parse_args()


class RadarComponent(QtWidgets.QWidget):
    def __init__(self, parent=None, port=None):
        """
        Initialize RadarComponent and set up GUI. This is called by QApplication. __init__ ()

        Args:
                port: Port of radar to connect to
        """
        super(RadarComponent, self).__init__()
        self.port = port
        layout = QtWidgets.QVBoxLayout()
        hbox_buttons = QtWidgets.QHBoxLayout()
        self.sbutton = QtWidgets.QPushButton("Start Radar")
        self.ebutton = QtWidgets.QPushButton("Stop Radar")
        self.cbutton = QtWidgets.QPushButton("Create Radar")

        self.sbutton.clicked.connect(self.start_radar)
        self.ebutton.clicked.connect(self.stop_radar)

        self.timer = QtCore.QTimer()
        self.plot_widget = pg.GraphicsLayoutWidget()

        self.rawplot = self.plot_widget.addPlot(title="Raw Data")
        self.rawplot.showGrid(x=True, y=True)
        self.rawplot.setLabel("left", "Amplitude")
        self.rawplot.setLabel("bottom", "Distance", "m")
        self.rawplot.setYRange(-0.04, 0.04)

        self.img = pg.ImageItem()

        self.img_array = np.zeros(
            (200, 312)
        )  # Second value must align with the number of bins
        self.specplot = self.plot_widget.addPlot(title="Spectrogram")
        self.specplot.addItem(self.img)
        self.specplot.setLabel("left", "Distance", "m")
        self.specplot.setLabel("bottom", "Time", "s")

        # bipolar colormap
        pos = np.array([0.0, 1.0, 0.5, 0.25, 0.75])
        color = np.array(
            [
                [0, 255, 255, 255],
                [255, 255, 0, 255],
                [0, 0, 0, 255],
                (0, 0, 255, 255),
                (255, 0, 0, 255),
            ],
            dtype=np.ubyte,
        )
        cmap = pg.ColorMap(pos, color)
        lut = cmap.getLookupTable(0.0, 1.0, 256)

        yscale = 1.0 * 1.5e8 / 23.328e9
        xscale = 1 / 20

        tr = pg.QtGui.QTransform()
        tr.scale(xscale, yscale)
        # tr.translate(0, 0.4)

        self.img.setTransform(tr)

        self.img.setLookupTable(lut)
        self.img.setLevels([0, 0.03])

        self.curveraw = self.rawplot.plot(pen=pg.mkPen("b", width=2))

        hbox_buttons.addWidget(self.sbutton)
        hbox_buttons.addWidget(self.ebutton)

        layout.addLayout(hbox_buttons)
        layout.addWidget(self.plot_widget)
        self.setLayout(layout)

    def start_radar(self):
        """
        Start Radar. This is called by start_thread () to start the thread that will send data
        """
        self.t = RadarThread(self, port=self.port)
        print("Start Radar")
        self.t.start()

    def stop_radar(self):
        """
        Stop radar and free resources. This is useful for debugging and to avoid leaking resources if you don't want to
        """
        print("Stop Radar")
        self.t.stop()
        del self.t


class RadarThread(QtCore.QThread):
    def __init__(self, parent=None, port=None):
        """
        Initialize the thread. This is the entry point for the RabbitThread class. We use RabbitMQManager to communicate with the rabbit server.

        Args:
                parent: The parent thread that is running this thread.
                port: The port to listen on for messages on the rabbit
        """
        super(RadarThread, self).__init__(parent)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        self.p = parent
        self.port = port
        self.record = list()
        parameters = pika.ConnectionParameters("127.0.0.1", 5672, "/")

        self.rabbit_manager = RabbitMQManager(parameters=parameters, port=self.p.port)
        self.rabbit_manager.start()
        self.rabbit_manager.messageChanged.connect(self.update)

    def update(self, frame):
        """
        Update the display with a new frame. This is called every frame to update the display by the time it takes to run the update.

        Args:
                frame: The frame to display in the display. The last frame is used as the time
        """
        self.record.append(frame)
        t = frame[-1]
        frame = np.array(frame[:-1])

        y = np.linspace(0.0, 2.0, num=312)
        self.p.img_array = np.roll(self.p.img_array, -1, 0)
        self.p.img_array[-1:] = abs(frame)
        self.p.curveraw.setData(y, frame)
        self.p.img.setImage(
            self.p.img_array,
            autoLevels=False,
        )

    def stop(self):
        """
        Save data to file and close rabbit connection. @return None @rtype : None @raise
        """
        nowtime = datetime.now()
        filename = (
            str(nowtime.hour)
            + "-"
            + str(nowtime.minute)
            + "-"
            + str(nowtime.second)
            + "-"
            + self.port
            + ".pkl"
        )
        print(len(self.record))
        file = open(filename, "wb")
        pickle.dump(self.record, file)
        file.close()
        self.record = list()
        try:
            self.rabbit_manager.connection.close()
        except:
            pass


class RabbitMQManager(QtCore.QObject):
    messageChanged = QtCore.pyqtSignal(list)

    def __init__(self, *, parameters=None, parent=None, port=None):
        """
        Initialize the connection. This is the entry point for the Pika client. You can pass parameters to the connection and it will be used to set the connection parameters

        Args:
                parameters: A dictionary of key value pairs that will be passed to the connection
                parent: The parent object that will be used to connect to the server
                port: The port to listen on for requests. If not specified the default port will be
        """
        super().__init__(parent)
        self.port = port
        self._connection = pika.BlockingConnection(parameters)

    @property
    def connection(self):
        """
        Gets the connection of this V1KubeVirtConfiguration. # noqa : E501 Specifies the connection to use for this configuration.


        Returns:
                The connection of this V1KubeVirtConfiguration if set otherwise None ( the default ). : type : : class : ` ~openstack. network. v2. connection. Connection
        """
        return self._connection

    def start(self):
        """
        Start consuming messages from RabbitMQ and call callback when messages arrive. This method is blocking indefinit
        """
        channel = self.connection.channel()
        channel.queue_declare(queue=self.port)
        print(self.port)
        channel.basic_consume(
            queue=self.port,
            on_message_callback=self._callback,
            auto_ack=True,
        )
        channel.queue_purge(queue=self.port)
        print(" [*] Waiting for messages. To exit press CTRL+C")
        self.t = threading.Thread(target=channel.start_consuming, daemon=True).start()

    def _callback(self, ch, method, properties, body):
        """
        Callback for the event. Emits the messageChanged signal with the data received from the server. It is used to update the state of the GUI and not to send messages to the user

        Args:
                ch: The channel that sent the event
                method: The method of the event ( GET POST etc. )
                properties: The properties of the event ( key value pairs )
                body: The body of the event ( json string )
        """
        data = json.loads(body)
        self.messageChanged.emit(data)


class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        """
        Initialize the widget. This is called by __init__ () and should not be called directly by user
        """
        super().__init__()
        self.radars = list()
        self.layout = QtWidgets.QVBoxLayout(self)
        self.sbutton = QtWidgets.QPushButton("Start All Radar")
        self.ebutton = QtWidgets.QPushButton("Stop All Radar")

        self.layout.addWidget(self.sbutton)
        self.layout.addWidget(self.ebutton)

        self.sbutton.clicked.connect(self.start_all_radar)
        self.ebutton.clicked.connect(self.stop_all_radar)

        for port in args.port:
            self.radars.append(RadarComponent(port=port))
            self.layout.addWidget(self.radars[-1])
        self.setLayout(self.layout)

    def start_all_radar(self):
        for i in range(len(self.radars)):
            self.radars[i].start_radar()

    def stop_all_radar(self):
        for i in range(len(self.radars)):
            self.radars[i].stop_radar()


# This function is called by the main window.
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
