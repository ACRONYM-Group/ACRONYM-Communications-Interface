import asyncio
import websockets
import json
from queue import SimpleQueue

from ACI.utils import make_blocking


connections = {}


async def _recv_handler(websocket, _, responses):
    """
    Handles a Server response

    :param websocket:
    :param _:
    :param responses:
    :return:
    """
    cmd = json.loads(await websocket.recv())

    if cmd["cmdType"] == "getResp":
        value = json.dumps(["get_val", cmd["key"], cmd["db_key"], cmd["val"]])
        responses.put(value)

    if cmd["cmdType"] == "setResp":
        value = json.dumps(["set_val", cmd["msg"]])
        responses.put(value)

    if cmd["cmdType"] == "ldResp":
        value = json.dumps(["ld", cmd["msg"]])
        responses.put(value)


class DatabaseInterface:
    """
        ACI Database Interface
    """
    def __init__(self, connection, db_key):
        self.conn = connection
        self.db_key = db_key

    @make_blocking
    async def _write_to_disk(self):
        """
        Write Database data to disk

        :return:
        """
        await self.conn.ws.send(json.dumps({"cmdType": "wtd", "db_key": self.db_key}))

    @make_blocking
    async def _read_from_disk(self):
        """
        Read Database data from disk

        :return:
        """
        await self.conn.ws.send(json.dumps({"cmdType": "rfd", "db_key": self.db_key}))

    @make_blocking
    async def _list_databases(self):
        """
        Get a list of all connected databases

        :return:
        """
        await self.conn.ws.send(json.dumps({"cmdType": "list_databases", "db_key": self.db_key}))
        return json.loads(await self.conn.wait_for_response("ld", None, self.db_key))

    @make_blocking
    async def _get_value(self, key):
        await self.conn.ws.send(json.dumps({"cmdType": "get_val", "key": key, "db_key": self.db_key}))
        response = await self.conn.wait_for_response("get_val", key, self.db_key)
        return response

    @make_blocking
    async def _set_value(self, key, val):
        await self.conn.ws.send(json.dumps({"cmdType": "set_val", "key": key, "db_key": self.db_key, "val": val}))

    def __getitem__(self, key):
        return self._get_value(key)

    def __setitem__(self, key, val):
        return self._set_value(key, val)
    
    def write_to_disk(self):
        self._write_to_disk()

    def read_from_disk(self):
        self._read_from_disk()

    def list_databases(self):
        return self._list_databases()


class Connection:
    """
        ACI Connection
    """
    def __init__(self, loop, ip, port, name):
        """
        :param ip:
        :param port:
        :param loop:
        """
        global connections

        self.ip = ip
        self.port = port
        self.ws = 0
        self.responses = SimpleQueue()
        self.loop = loop
        self.name = name

        self.interfaces = {}

        connections[name] = self

    def start(self):
        self._create(self.port, self.ip, self.loop, self.responses)

    async def wait_for_response(self, _, key, db_key):
        """
        Waits for a response
        :param _:
        :param key:
        :param db_key:
        :return:
        """
        while True:
            if not self.responses.empty():
                value = self.responses.get_nowait()
                cmd = json.loads(value)
                if tuple(cmd)[:3] == ("get_val", key, db_key):
                    return cmd[3]
                elif tuple(cmd)[:3] == ("set_val", key, db_key):
                    return cmd[3]
                elif cmd[0] == "ld":
                    return cmd[1]

    def _create(self, port, ip, loop, responses):
        """
        Initializes the connection

        :param port:
        :param ip:
        :param loop:
        :param responses:
        :return:
        """
        asyncio.set_event_loop(loop)
        asyncio.get_event_loop().run_until_complete(self.handler(loop, responses, ip, port))
        asyncio.get_event_loop().run_forever()

    async def handler(self, loop, responses, ip="127.0.0.1", port=8765):
        """
        Creates a handler

        :param loop:
        :param responses:
        :param ip:
        :param port:
        :return:
        """
        asyncio.set_event_loop(loop)
        uri = "ws://%s:%s" % (ip, port)

        async with websockets.connect(uri) as websocket:
            self.ws = websocket
            while True:
                consumer_task = asyncio.ensure_future(_recv_handler(self.ws, uri, responses))

                done, pending = await asyncio.wait([consumer_task], return_when=asyncio.FIRST_COMPLETED)

                for task in pending:
                    task.cancel()

    def _get_interface(self, database_key):
        """
        Gets an interface to the Database with the given keys

        :param database_key:
        :return:
        """
        return DatabaseInterface(self, database_key)

    def __getitem__(self, key):
        if key not in self.interfaces:
            self.interfaces[key] = self._get_interface(key)
        return self.interfaces[key]
