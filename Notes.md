# Notes

## Parts
1. Loop watching for incoming messages
2. Loop sending out messages - NOW DEPRECATED
3. Loop responding to mesages - socketserver (UDP)
4. Function(s) doing stuff (sending messages, updating list of peers, downloading new files and indexes)
5. Loop that watches the user folder
6. Loop responding to index and file requests - http server

## General
- What loops can be combined?
- What messages will 4 send out?
	- On boot to notify other nodes that this one exists now
    	- All nodes that receive the message respond to it with a REPLY message type, and this node records their addresses
    	- To be used for `lfctl refresh`
    	- The refresh function is run on boot after all the nodes reply, to get the files other nodes are currently holding
    	- Will be called an EXIST type message, to notify nodes of its existence
    	- **Any node that receives this type of message in any context will record the sender's address for later, making it useful for peering**
    	- **Any node that recieves this message should also get the index of the sender, to get any files it already is sharing**
	- When a new file is added or a file is changed
    	- Different message type
    	- Should the message just say FILE?
    	- Then nodes will need to get that node's index and see what has been changed themselves
    	- Instead it could contain all the index information for that file only
    	- **Technically this means we don't need an index anymore**
    	- Although UDP means some file updates could be missed
    	- So every so often nodes can refresh, checking in with all known nodes - or user can run `lfctl refresh`
- 1 should call 4 and get it to add/update the node's info to some file or whatever
- 6 should somehow respond in a new process or thread each time
- Handle if there's the same UUID, but IP address has changed
  - Update IP and look at index just in case
- Version values should be stored for each file
- File updates increment the value by one
- File updates with a lower value will be rejected
  - ie someone updating the file without having the newest update
  - Could this result in a fragmented network?
  - A rebroadcast of a newer update should fix things
- Philosophy: Less for editing, more for sharing static files - but editing should work to a degree
- Nodes must maintain an index, to give to refreshing nodes
- New files found from messages must be appended to the index, after getting the file successfully (in case there's an error retrieving it)
- When contacting peers
  - Go through UUIDs in `peers`
  - Try first IP address associated with it
  - If it fails go to the next, etc
- Refresh sequence
  - Contact the first peer as defined above, requesting their index
  - Compare **the hash provided along with the index** to our one
  - If they are the same, discard the provided index and move on
  - If they are different, go through the index and request files from the node if they are new or have a higher version number than the current one stored in `self_index`
    - Update `self_index`
  - Move on to the next peer in the peers file

## To Do
- Add a config file
  - Addresses broadcast to (so as not to constantly use `lfctl add`)
  - Name of software in UDP message, to allow concurrent networks (`Lan-Folder2;`, etc)
  - Disabling IPv4 or IPv6
  - Changing `lfctl` and server ports
  - Max size - add a check within software to make sure the new downloaded file will not exceed this
- Type up standard when complete - message data, server hooks, etc
- LOGGING
I can write good
- Deleting files on stop, or moving them, etc

## Commandline application
- `lfctl` - LAN-Folder controller
- `lfctl [start, stop, refresh, add, remove, listpeers, restore]`
- `add` should check who responds to the address provided, in case it is a gateway/multicast/broadcast address
  - Add each replier to the peer list, used by `listpeers`
- `restore` with no arguments moves the files from the latest folder in `old-files` into `shared-folder` and deletes the files
- `restore` with a datetime argument moves that folder's contents instead
- Communicates to some other server loop through another port
- UDP or TCP? - I'm thinking UDP

## Message format
- `<something>` indicates a variable area
- All messages are UDP, to a broadcast/multicast address, or directly to a node's IP
- The `<path>` variable is the local path from the file directory used by the application
  - It does not begin with a slash
- `<number>` is an incrementing number
- `<bytes>` is the size of the file

EXIST - when the node is started up, or for manual peering:

`LAN-Folder;type;EXIST;uuid;<uuid>`

REPLY - to reply to EXIST messages, which completes the peering

`LAN-Folder;type;REPLY;uuid;<uuid>`

FILE - for file updates or additions:

`LAN-Folder;type;FILE;uuid;<uuid>;path;</path/to/file.ext>;ver;<number>;size;<bytes>`

## Folder structure
```
lfctl - file for the lfctl tool - run this
main.py - main file
uuid
shared-folder/ - files and folders to be shared with peers go here
	...
old-files/ - where files from previous times are stored
	<datetime>/ - folders of files, named by datetime of shutdown or next start
		...
	...
default-files/ - files to be auto-shared on boot every time
	...
```

## Internal formats
- `.data/uuid` - plaintext, one line
- `peers` - A dictionary that has been stored in json format - `{<uuid>: [[<ip>, port],],}`
- `self_index` - Listing of files in json format, taken from indexes and UDP messages - `{<path>: {"ver": <number>, "size": <bytes>},}`
- `self_index_hash` - sha256 hash of `self_index`
- `old-files` - A folder that stores files from previous times the node was running. Every time the node shuts down (or starts again after an error in shutdown), everything in `shared-folder` is moved to `old-files`, so that if the node starts up again in a new environment, it doesn't start sharing everything from last time. There are sub-folders as noted above. This folder should be cleared out by the user manually.
- `default-files` - any files placed here will be moved to `shared-folder` and added to the index automatically at boot. This is for small files (so as not to attack your peers) that you often want to share, maybe your PGP key.

## HTTP server
- All HTTP GET requests
- `/index` to get the json index of the node
- `/file/path/to/file.ext` for getting a file from a node