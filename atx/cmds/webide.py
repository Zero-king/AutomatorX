# coding: utf-8

import os
import sys
import logging
import webbrowser
import socket
import time

import tornado.ioloop
import tornado.web
import tornado.websocket
from tornado.concurrent import run_on_executor
from concurrent.futures import ThreadPoolExecutor   # `pip install futures` for python2

from atx import logutils
from atx import base


__dir__ = os.path.dirname(os.path.abspath(__file__))

log = logutils.getLogger("webide")
log.setLevel(logging.DEBUG)


IMAGE_PATH = ['.', 'imgs', 'images']
workdir = '.'

def read_file(filename, default=''):
    if not os.path.isfile(filename):
        return default
    with open(filename, 'rb') as f:
        return f.read()

def write_file(filename, content):
    with open(filename, 'w') as f:
        f.write(content.encode('utf-8'))

def get_valid_port():
    for port in range(10010, 10100):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        if result != 0:
            return port

    raise SystemError("Can not find a unused port, amazing!")

class AtxLogHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        print('RR:', log_entry)

def _init():
    hdlr = AtxLogHandler()
    hdlr.setLevel(logging.DEBUG)
    fmt = "%(asctime)s %(levelname)-8.8s [%(name)s:%(lineno)4s] %(message)s"
    hdlr.setFormatter(logging.Formatter(fmt))
    log = logging.getLogger('atx')
    log.addHandler(hdlr)
    log.setLevel(logging.DEBUG)

_init()

class FakeStdout(object):
    def __init__(self, fn=sys.stdout.write):
        self._fn = fn

    def write(self, s):
        self._fn(s)

    def flush(self):
        self._fn('flush\n')

class MainHandler(tornado.web.RequestHandler):
    def get(self):
        imgs = base.list_images(path=IMAGE_PATH)
        imgs = [(os.path.basename(name), name) for name in imgs]
        self.render('index.html', images=imgs)

    def post(self):
        print self.get_argument('xml_text')
        self.write("Good")


class EchoWebSocket(tornado.websocket.WebSocketHandler):
    executor = ThreadPoolExecutor(max_workers=1)

    def open(self):
        print("WebSocket connected")

    def _highlight_block(self, id):
        self.write_message({'type': 'highlight', 'id': id})
        time.sleep(1.0)

    def write_console(self, s):
        self.write_message({'type': 'console', 'output': s})

    def run_blockly(self):
        content = ''
        filename = 'blockly.py'
        with open(filename, 'rb') as f:
            content = f.read()
        fake_sysout = FakeStdout(self.write_console)

        __sysout = sys.stdout
        sys.stdout = fake_sysout
        exec content in {
            'highlight_block': self._highlight_block,
            '__name__': '__main__',
            '__file__': filename}
        sys.stdout = __sysout
        
    @run_on_executor
    def background_task(self, i):
        self.write_message({'type': 'run', 'status': 'running'})
        self.run_blockly()
        return i

    @tornado.gen.coroutine
    def on_message(self, message):
        print(message)
        self.write_message({'type': 'console', 'output': '# echo hello\n'})
        if message == 'refresh':
            imgs = base.list_images(path=IMAGE_PATH)
            imgs = [dict(
                path=name.replace('\\', '/'), name=os.path.basename(name)) for name in imgs]
            self.write_message({'type': 'image_list', 'data': list(imgs)})
        elif message == 'run':
            res = yield self.background_task(4)
            self.write_message({'type': 'run', 'status': 'ready', 'result': res})
        else:
            self.write_message(u"You said: " + message)

    def on_close(self):
        print("WebSocket closed")
    
    def check_origin(self, origin):
        return True


class WorkspaceHandler(tornado.web.RequestHandler):
    def get(self):
        ret = {}
        ret['xml_text'] = read_file('blockly.xml', '<xml xmlns="http://www.w3.org/1999/xhtml"></xml>')
        ret['python_text'] = read_file('blockly.py')
        self.write(ret)

    def post(self):
        log.debug("Save workspace")
        xml_text = self.get_argument('xml_text')
        python_text = self.get_argument('python_text')
        write_file('blockly.xml', xml_text)
        write_file('blockly.py', python_text)


class StaticFileHandler(tornado.web.StaticFileHandler):
    def get(self, path=None, include_body=True):
        path = path.encode(base.SYSTEM_ENCODING) # fix for windows
        return super(StaticFileHandler, self).get(path, include_body)


def make_app(settings={}):
    static_path = os.getcwd()
    application = tornado.web.Application([
        (r"/", MainHandler),
        (r"/workspace", WorkspaceHandler),
        (r'/static_imgs/(.*)', StaticFileHandler, {'path': static_path}),
        (r'/ws', EchoWebSocket),
    ], **settings)
    return application


def main(**kws):
    application = make_app({
        'static_path': os.path.join(__dir__, 'static'),
        'template_path': os.path.join(__dir__, 'static'),
        'debug': True,
    })
    port = kws.get('port', None)
    if not port:
        port = get_valid_port()

    global workdir
    workdir = kws.get('workdir', '.')

    open_browser = kws.get('open_browser', True)
    if open_browser:
        url = 'http://127.0.0.1:{}'.format(port)
        webbrowser.open(url, new=2) # 2: open new tab if possible

    application.listen(port)
    log.info("Listening port on 127.0.0.1:{}".format(port))
    tornado.ioloop.IOLoop.instance().start()

if __name__ == "__main__":
    main()