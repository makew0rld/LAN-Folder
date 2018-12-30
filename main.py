"""Main file that starts all other processes."""

import os
from uuid import uuid4
import socket
from time import sleep
import multiprocessing as mp
import socketserver as ss
import requests
import shutil
from time import asctime


# Declare constants here
# XXX: most of these will be configuration file candidates
NAME = "LAN-Folder"
PORT = 12777
SHARED_FOLDER = "shared-folder"  # Folder for shared files
OLD_FILES = "old-files"  # Folder for old files
DEFAULT_FILES = "default-files"  # Folder for default files
TIMEOUT = 3  # Timeout in seconds before a server connection is stopped - used for requests.get

class Message:
    """Methods for sending out UDP messages."""

    global self_index

    def __init__(self, uuid=UUID, port=PORT, ipv4_dests=[], ipv6_dests=[]):
        self.uuid = uuid
        self.port = port
        self.ipv4_dests = ipv4_dests  # List
        self.ipv6_dests = ipv6_dests  # List

    def send_message(self, payload):
        """Sends a generic message with the specified payload, to previously specified destinations."""

        payload = payload.encode()  # Bytes

         # IPv4
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)  # Required for broadcast messages - won't affect non-broadcast addressed messages
        for dest in self.ipv4_dests:
            try:
                sock.sendto(payload, (dest, self.port))
            except socket.error:
                continue
        # IPv6
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        for dest in self.ipv6_dests:
            try:
                sock.sendto(payload, (dest, self.port))
            except socket.error:
                continue

    def exist_message(self, send=True):
        """Sends a UDP packet to previously specified destinations, to announce that this node exists.
        
        This message may be sent, on boot of the node, or for manual peering.
        Any node that receives this message should mark down the sender's UUID and address for later use, as well as
        request that node's files.
        If send is false, it will just return the message payload (encoded).
        """
        
        payload = NAME + ";type;EXIST;uuid;" + self.uuid
        if send:
            self.send_message(payload)
        else:
            return payload.encode()
    
    def reply_message(self, send=True):
        """Sends a UDP packet to previously specified destinations, to reply to an EXIST message and complete peering.

        Any node that receives this message should mark down the sender's UUID and address for later use.
        If send is false, it will just return the message payload (encoded).
        """

        payload = NAME + ";type;REPLY;uuid;" + self.uuid
        if send:
            self.send_message(payload)
        else:
            return payload.encode()

    def file_message(self, path, ver=None, send=True):
        """Sends a UDP packet to previously specified destinations, to announce the specified file has been updated/added.
        
        If send is false, it will just return the message payload (encoded).
        """

        # XXX: does not update any metadata (hash, version num) - that should happen before
        if ver == None:
            ver = self_index[path]["ver"]
        file_bytes = self_index[path]["size"]
        payload = NAME + ";type;FILE;uuid;" + self.uuid + ";path;" + path + ";ver;" + ver + ";size;" + file_bytes
        if send:
            self.send_message(payload)
        else:
            return payload.encode()


class MyUDPHandler(ss.BaseRequestHandler):
    """Handles receiving UDP messages and calls the appropriate functions."""

    # TODO: Have each message initiate a Process, then have that handling thread wait for it to return the
    #       state variables to change, through a SimpleQueue - TODO: DOCUMENT THIS

    global peers, self_index

    def handle(self):
        data = self.request[0].strip()
        socket = self.request[1]
        if data[:22] == NAME.encode() + b";type;EXIST;":
            uuid = data[data.find(";uuid;")+6:]
            add_peer(uuid, self.client_address)
            # Reply to them
            socket.sendto(Message().reply_message(send=False), self.client_address)
            their_index = get_index(self.client_address)
            # Go through the index and download files in a process
            queue = mp.SimpleQueue()
            p = mp.Process(target=go_through_index, args=(their_index, self.client_address, queue))
            p.start()  # XXX: should this be kept track of somewhere to kill?
            # Wait for a response
            while True:
                if not queue.empty():
                    answer = queue.get()
                    if answer != False:  # The index was updated
                        # Update it for everyone then
                        self_index = answer
                    break  # Stop handling
        elif data[:22] == NAME.encode() + b";type;REPLY;":
            uuid = data[data.find(";uuid;")+6:]
            add_peer(uuid, self.client_address)  
            their_index = get_index(self.client_address)
            # Go through the index and download files in a process
            queue = mp.SimpleQueue()
            p = mp.Process(target=go_through_index, args=(their_index, self.client_address, queue))
            p.start()  # XXX: should this be kept track of somewhere to kill?
            # Wait for a response
            while True:
                if not queue.empty():
                    answer = queue.get()
                    if answer != False:  # The index was updated
                        # Update it for everyone then
                        self_index = answer
                    break  # Stop handling
        elif data[:21] == NAME.encode() + b";type;FILE;":
            # XXX: will all this string manipulation work?
            uuid = data[data.find(";uuid;")+6:data.find(";", data.find(";uuid;")+6)]  # XXX: for logging
            path = data[data.find(";path;")+6:data.find(";", data.find(";path;")+6)]
            ver  = data[data.find(";ver;")+5:data.find(";", data.find(";ver;")+5)]
            size = data[data.find(";size;")+6:]
            # Download the file in a separate process
            queue = mp.SimpleQueue()
            p = mp.Process(target=get_file_and_update_index, args=(path, ver, size, self.client_address, queue))
            p.start()  # XXX: should this be kept track of somewhere to kill?
            # Wait for a response
            while True:
                if not queue.empty():
                    answer = queue.get()
                    if answer != False:  # The index was updated
                        # Update it for everyone then
                        self_index = answer
                    break  # Stop handling
                    
class MyUDPServer(ss.ThreadingUDPServer):
    """Threading UDPServer with custom IPv6 support settings."""

    def server_bind(self):
        # IPv4 receiving should work on dual-stack machines, even with the following IPv6 settings
        self.address_family = socket.AF_INET6  # XXX: should it NOT be self. ?
        # XXX: Following code is from Forban, we'll see if it works
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        self.socket.bind(self.server_address)


def run_server():
    """Sets up and runs the server using its classes."""

    server = MyUDPServer(("::", PORT), MyUDPHandler)
    server.serve_forever()

message_server = mp.Process(target=run_server)

def get_index(address):
    """Returns the index of the specified node in python format.
    
    The address param is a tuple or list: [ip, port]
    False is returned if the index could not be retrieved for any reason.
    """

    # Use brackets in case it is IPv6 - will still work with IPv4
    url = "http://[" + address[0] + "]:" + address[1] + "/index"
    req = requests.get(url, timeout=TIMEOUT)
    try:
        return req.json()
    except:
        return False
    if req.status_code != 200:
        return False

def update_index(path, ver, size, queue=None):
    """Updates this node's index for a file with the provided information.
    
    The size param is in bytes.
    A file message may need to be sent afterward, if the change was local to this node.
    The queue param is for communicated values out of processes, and is optional.
    """

    global self_index

    self_index[path] = {"ver": ver, "size": size}
    if queue != None:
        queue.put(self_index)

def get_file(path, address):
    """Downloads the specified file from the specified node.
    
    The path param should not begin with a slash, and should just be the
        local path to the file from the shared-folder directory.
    The address param is a tuple or list: [ip, port]
    False is returned if the file could not be retrieved for any reason.
    True is returned if successful.
    """
    
    # Use brackets in case it is IPv6 - will still work with IPv4
    url = "http://[" + address[0] + "]:" + address[1] + "/" + path
    req = requests.get(url, timeout=TIMEOUT)
    if req.status_code != 200:
        return False
    folders = os.path.dirname(path)
    # Create subfolders for the file as needed
    os.makedirs(SHARED_FOLDER+"/"+folders, exist_ok=True)
    with open(SHARED_FOLDER+"/"+path, "wb") as f:
        f.write(req.content)
    return True

def add_peer(uuid, address):
    """Adds a peer to the peer dictionary.
    
    The address param is a tuple or list: [ip, port]
    """

    global peers

    if uuid in peers:
        # Check if IP address is new
        if address not in peers[uuid]:
            peers[uuid].append(address)
    else:  # Add the peer
        peers[uuid] = [address]

def go_through_index(index, address, queue=None):
    """Goes through the provided index, and downloads files that are new to this node, updating the index too.
    
    The index is a python dictionary.
    The address param is a tuple or list: [ip, port]
    The queue param is for communicated values out of processes, and is optional.
    """

    global self_index

    updated_files = 0

    for path in index.keys():
        if path not in self_index.keys():  # New file
            success = get_file_and_update_index(path, index[path]["ver"], index[path]["size"], address)
            if success:
                updated_files += 1
        else:  # Old file
            # Check version number to see if it's a newer version
            if index[path]["ver"] > self_index[path]["ver"]:
                success = get_file_and_update_index(path, index[path]["ver"], index[path]["size"], address)
                if success:
                    updated_files += 1
            else:
                # XXX: Logging that an older version was found, and nothing needs to be done
                pass
    
    if updated_files == 0 and queue != None:
        # Tell the queue that nothing happened, so the thread doesn't keep waiting for an answer
        queue.put(False)


def get_file_and_update_index(path, ver, size, address, queue=None):
    """Downloads a file and updates the index if the download was successful.

    The address param is a tuple or list: [ip, port]
    The path param should not teach with a slash.
    The queue param is for communicated values out of processes, and is optional.
    False is returned if the download was unsuccessful.
    True is returned if it is.
    """

    success = get_file(path, address)
    if success:
        update_index(path, ver, size, queue)
        return True
    else:
        # XXX: Logging
        if queue != None:
            # Tell the queue that nothing happened, so the thread doesn't keep waiting for an answer
            queue.put(False)
        return False


# Create all the required folders and files if they don't already exist - they should though
folder_contents = os.listdir()
# uuid
if "uuid" in folder_contents:
    with open("uuid", "r") as f:
        UUID = f.readline().strip()
else:
    with open("uuid", "w") as f:
        UUID = uuid4()  # Generate a random uuid on first start, when there is no uuid file
        f.write(UUID)
# shared-folder - could be outside local directory
if os.path.isdir(SHARED_FOLDER):
    if os.listdir(SHARED_FOLDER) != []:  # There are files in there at boot - bad
        # Move contents from last time, and create a date directory for them
        # This means a graceful shutdown didn't happen
        date_dir = OLD_FILES + "/" + asctime()
        os.mkdir(date_dir)
        for file_or_folder in os.listdir(SHARED_FOLDER):
            shutil.move(file_or_folder, date_dir)
else:
    os.makedirs(SHARED_FOLDER)
# old-files
if not os.path.isdir(OLD_FILES):
    os.makedirs(OLD_FILES)
# default-files
if not os.path.isdir(DEFAULT_FILES):
    os.makedirs(DEFAULT_FILES)
# log
if not os.path.isdir("log"):
    os.mkdir("log")

# Global state variables
peers = {}
self_index = {}

# TODO: load files from default files, and add to index

# Announce once upon node boot to notify peers that this node has started
message = Message(ipv6_dests=["255.255.255.255"], ipv4_dests=["ff02::1"])  # LAN addresses
message.exist_message()

# TODO: Some final loop for this file that can stop kill all the child processes when asked to by lfctl?