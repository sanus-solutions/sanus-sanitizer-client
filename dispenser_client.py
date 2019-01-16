import sys, os, time, json, threading, queue, requests, io, base64, picamera, logging, random, datetime, configparser
import numpy as np 
import RPi.GPIO as GPIO
from PIL import Image

'''
Basic Structure 
dispenser client(main loop)
    --> http thread (sub loop of dispenser client, timely http request )
        --> second http thread (sub loop of http thread, less urgent request)
'''

class DispenserClient:
    def __init__(self, config='config.ini'):
        try: 
            config = configparser.ConfigParser()
            config.read(config)
        except:
            raise Exception("config.ini file missing.")

        ## Logger
        level = self.log_level(config['DEBUG']['LogLevel'])
        self.logger = logging.getLogger(config['PROPERTY']['Type'])
        self.logger.setLevel(level)
        ch = logging.StreamHandler()
        ch.setLevel(level)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)

        #Route 
        self.route = config['SERVER']['Route']

        #Camera 
        self.camera = picamera.PiCamera()
        self.camera.resolution = config['CAMERA']['Resolution']
        self.node_id = config['PROPERTY']['Id']
        self.shape = config['Camera']['Shape']
        size = (config['Camera']['Width'], config['Camera']['Height'], config['Camera']['Channel'])
        self.image = np.empty(size, dtype=np.uint8)
        self.camera.start_preview(fullscreen=int(cofnig['Camera']['FullScreen']), window = (100,20,0,0))
        self.logger.debug('dispenser client camera initialized, start_preview executed')
        
        # GPIO - LED & Distance Sensor
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(4, GPIO.IN) #motion sensor
        self.logger.debug('dispenser client GPIO check')

        # temporary data structure for storage
        self.payload_queue =  queue.Queue() # If length no supply for queue, it's dynamics
        self.logger.debug('dispenser client payload queue initialized') 

        # http thread instantiate 
        self.http = http_thread("http thread", self.node_id, type, unit, self.payload_queue)
        self.http.daemon = True 
        self.http.start()
        self.logger.debug('dispenser client http thread initialized')

    def log_level(self, level):
        if level == 'Info':
            return logging.INFO
        else:
            return logging.DEBUG

    def capture(self):
        self.camera.capture(self.image, 'rgb')
        image_temp = self.image.astype(np.float64)
        image_64 = base64.b64encode(image_temp).decode('ascii')
        payload = {'NodeID': self.node_id, 'Timestamp': time.time() ,'Image': image_64, 'Shape': self.shape}
        headers = {'Content_Type': 'application/json', 'Accept': 'text/plain'}
        self.payload_queue.put((payload, headers, self.route)) # dispenser thread
        self.logger.debug('payload: %s, headers: %s', str(payload), str(headers))

    def update_route(self, new_route):
        self.route = new_route

    def update_node_id(self, new_node_id):
        self.node_id = new_node_id

    def update_unit(self, new_unit):
        self.unit = new_unit

class http_thread(threading.Thread):
    def __init__(self, name, node_id, type, unit, payload_queue):
        ###########################################################################################
        # Logger
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger('http thread(First attempt)')
        handler = logging.FileHandler('http_thead.log')
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        ###########################################################################################

        # Initialize thread
        threading.Thread.__init__(self)
        self.name = name
        self.node_id = node_id
        self.type = type
        self.unit = unit
        self.payload_queue = payload_queue
        self.storage_queue = queue.Queue()

        # second_http thread instantiate 
        self.second_http = second_http_thread("http thread", node_id, type, unit, self.storage_queue)
        self.second_http.daemon = True 
        self.second_http.start()
        self.logger.debug('dispenser client second http thread initialized')


    def run(self):
        while 1:
            if self.payload_queue.qsize():
                payload, headers, route = self.payload_queue.get()
                try:
                    result = requests.post(route, json=payload, headers=headers)
                    code = result.status_code
                    if code == 200:
                        self.logger.info('HTTP request received. ' + result.json()["Status"])
                    else:
                        self.storage_queue.put((payload, headers, route))
                except:
                    self.logger.info("Failed to establish connection with server. Try again in 5s.")
                    self.storage_queue.put((payload, headers, route))

class second_http_thread(threading.Thread):
    def __init__(self, name, node_id, type, unit, storage_queue):
        ###########################################################################################
        # Logger
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger('http thread(Second attempt)')
        handler = logging.FileHandler('second_http.log')
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s') 
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        ###########################################################################################

        # Initialize thread
        threading.Thread.__init__(self)
        self.name = name
        self.node_id = node_id
        self.type = type
        self.unit = unit
        self.storage_queue = storage_queue

    def run(self):
        while 1:
            if self.storage_queue.qsize(): 
                time.sleep(5) # wait for 5 seconds before second attempt 
                payload, headers, route = self.storage_queue.get()
                try:
                    result = requests.post(route, json=payload, headers=headers) 
                    code = result.status_code
                    if code == 200:
                        self.logger.info("second attempt successful: " + result.json()["Status"])
                    else:
                        self.logger.info("second attempt failed with code: " + str(code))
                        self.storage_queue.put((payload, headers, route))
                except:
                    self.storage_queue.put((payload, headers, route))
                    self.logger.info("Failed to establish connection with server again. Try again in 30s.")
                    time.sleep(25)

if __name__ == "__main__":

    # Initialization
    client = DispenserClient('demo_sanitizer')

    #Main loop
    while 1:
        try:
            if GPIO.input(4):
                time.sleep(0.25)
            else:
                cur_time = time.time()
                respond = client.capture()
                logger.info('capture successfully, camera captured images returns in:' +
                    '%f s, now forwarding payload to http thread.', time.time() - cur_time)
                time.sleep(2)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt")
            sys.exit()
