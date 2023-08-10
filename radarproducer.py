import asyncio
import sys, signal

import pika

import pymoduleconnector
from pymoduleconnector import DataType

from time import sleep
import numpy as np
import threading
import time
import os
import json
import pickle
import argparse


exitFlag = 0


class Worker(threading.Thread):
    def __init__(self, threadID, name, counter):
        """
        Initializes the worker. Must be called before use. It is the responsibility of the caller to ensure that threadID is valid

        Args:
                threadID: Thread ID of the worker
                name: Name of the worker ( used for logging )
                counter: Counter of the worker ( used for logging )
        """
        super(Worker, self).__init__()
        self.threadID = threadID
        self.name = name
        self.counter = counter

    def run(self):
        """
        Run radar and print results. This is the entry point for the class
        """
        print("Starting " + self.name)
        print(self.name)
        run_radar(self.name)
        print("Exiting " + self.name)


def run_radar(threadName):
    """
    Runs radar and returns the result. This is a blocking call so it should be run in a seperate thread

    Args:
        threadName: name of the thread to run radar

    Returns:
        tuple of ( success_code error_code )
    """

    def reset(device_name):
        """
        Reset the XEP - 0040 module. This is a soft reset to ensure that it is ready to start a new test run

        Args:
                device_name: the name of the
        """
        mc = pymoduleconnector.ModuleConnector(device_name)
        xep = mc.get_xep()
        xep.module_reset()
        mc.close()
        sleep(3)

    def read_frame():
        """
        Reads and returns frame from XEP - 333. This function is used to read and convert the frame from XEP - 333 to numpy array


        Returns:
                numpy array of frame
        """
        # Gets frame data from module
        d = xep.read_message_data_float()
        frame = np.array(d.data)
        # Convert the resulting frame to a complex array if downconversion is enabled
        return frame

    def update():
        """
        Update the thread by sending a frame to rabbitmq. This is called every frame
        """
        frame = read_frame().tolist()
        frame.append(time.time())
        message_body = json.dumps(
            frame
        )  # convert numpy to json byte file such that it can be sent over rabbitmq
        channel.basic_publish(exchange="", body=message_body, routing_key=threadName)

    device_name = threadName
    reset(threadName)  # clear buffer
    mc = pymoduleconnector.ModuleConnector(device_name)
    xep = mc.get_xep()
    xep.x4driver_set_dac_min(900)
    xep.x4driver_set_dac_max(1150)

    # Set integration
    xep.x4driver_set_iterations(16)
    xep.x4driver_set_pulses_per_step(26)

    xep.x4driver_set_tx_center_frequency(4)
    xep.x4driver_set_frame_area(0, 2)
    xep.x4driver_set_fps(20)

    connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
    channel = connection.channel()

    # Update the current state of the game.
    while True:
        update()


def signal_handler(signal, frame):
    """
    Signal handler for nprogram. This is called when a signal is received.

    Args:
        signal: The signal received by the signal handler. It is passed as an argument to the signal handler.
        frame: The stack frame associated with the signal. It is passed as an argument to the signal handler
    """
    print("\nprogram exiting gracefully")
    sys.exit(0)


# This is a worker thread that handles the signal.
if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)  # Receive ctrl+c signal
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=str, nargs="+", default="")
    args = parser.parse_args()
    radars = list()

    i = 1

    print(args.port)

    for port in args.port:
        radars.append(Worker(i, port, i))
        #radars[] = Worker(1, args.port, 1)
        radars[-1].start()
        i+=1

    #thread.run()
