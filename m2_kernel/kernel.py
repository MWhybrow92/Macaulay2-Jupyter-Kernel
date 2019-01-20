import argparse
import configparser
import pexpect
import re
import os
from ipykernel.kernelbase import Kernel
from . import __version__

""" Macaulay2 Jupyter Kernel
"""


class M2Config:
    """"""
    
    def __init__(self, execpath, configpath=os.getenv('M2JK_CONFIG')):
        """"""
        parser = argparse.ArgumentParser(usage=argparse.SUPPRESS)
        config = configparser.ConfigParser(allow_no_value=True)

        parser.add_argument('--timeout', type=int, default=2)
        parser.add_argument('--timeout_startup', type=int, default=5)
        parser.add_argument('--mode', choices=['default', 'texmacs', 'pretty'], default='default')
        parser.add_argument('--tb', default=False,
            type=lambda x: True if x.lower() in ['1','true','on'] else False)
        parser.add_argument('--theme', choices=['default', 'emacs'], default='default')
        # execpath is now mutable, but modifying it is no-op. fix this
        parser.add_argument('--execpath', default=execpath)
        
        parser.add_argument('--version', action='store_const', const=__version__, default=__version__)
        parser.add_argument('--configpath', action='store_const', const=configpath, default=configpath)
        parser.add_argument('--config')
        
        args = parser.parse_args('')
        
        if configpath:
            config.read(configpath)
            line = ' '.join(['--{} {}'.format(key, val) for key, val in config.items('magic')])
            args = parser.parse_known_args(line.split(), args)
        
        self.parser = parser
        self.config = config
        self.args = args

    def read(self, line):
        """"""
        self.config.remove_section('temp')
        try:
            self.config.read_string('[temp]\n'+line)
            key, val = self.config.items('temp')[0]
            if key in self.args:
                self.args = self.parser.parse_args('--{} {}'.format(key, val).split(), self.args)
            message = '[magic successed] {} = {}'.format(key, self.args.__dict__[key])
        except:
            key, val = None, None
            message = '[magic failed]'
        return key, val, message


class M2Kernel(Kernel):
    """ the M2 kernel for Jupyter
    """
    implementation = 'macaulay2_jupyter_kernel'
    implementation_version = __version__
    banner = 'Macaulay2 thru Jupyter'
    language = 'Macaulay2'
    language_version = '1.13.0.1'  # "defining implementation" version
    language_info = {
        'name': 'Macaulay2',
        'mimetype': 'text/x-macaulay2',
        'file_extension': '.m2',
        'codemirror_mode': 'macaulay2',
        # 'pigments_lexer': None,
    }

    patt_consume = re.compile(r'((?:.*))\r\ni(\d+)\s:\s', re.DOTALL)
    patt_emptyline = re.compile(r'^\s*$')
    patt_magic = re.compile(r'\s*--\s*\%(.*)$', re.DOTALL)
    patt_comment = re.compile(r'\s*--.*$', re.DOTALL)
    patt_texmacs = re.compile(r'\x02html:(.*)\x05', re.DOTALL)

    nonkernelrun = False

    def __init__(self, *args, **kwargs):
        """ kernel init - calls __init__ on the parent and sets up the proc and conf
        """
        super().__init__(*args, **kwargs)
        self.conf = M2Config(pexpect.which('M2'))
        execpath = self.conf.args.execpath
        if not execpath:
            raise RuntimeError("M2JK: M2 not found")
        modes_init = """
            m2jkModeStandard = Thing#{Standard,Print};
            m2jkModeTeXmacs = Thing#{TeXmacs,Print};
            """
        self.proc = pexpect.spawn('{} -e "{}"'.format(execpath, modes_init), encoding='UTF-8')
        self.proc.expect(self.patt_consume, timeout=self.conf.args.timeout_startup)

    def preprocess(self, code):
        """"""
        magic_lines = []
        code_lines = []
        for line in code.splitlines():
            if self.patt_emptyline.match(line):
                pass
            elif self.patt_magic.match(line):
                magic_lines.append(self.process_magic(self.patt_magic.match(line).groups()[0]))
            elif self.patt_comment.match(line):
                pass
            else:
                code_lines.append(line+'--CMD')
        if magic_lines or code_lines:
            return '{}{}{}--EOB'.format('\n'.join(magic_lines),
                                        '\n' if magic_lines and code_lines else '',
                                        '\n'.join(code_lines))
        return ''

    def process_magic(self, raw_magic):
        """"""
        key, val, msg = self.conf.read(raw_magic)
        retop = 'null'

        if self.nonkernelrun:
            print(msg)
        else:
            self.send_stream(msg)

        if key == 'config':
            if val == 'print':
                content = str(self.conf.args)
                if self.nonkernelrun:
                    print(content)
                else:
                    self.send_stream(content)
            elif val == 'reset':
                self.conf = M2Config(self.conf.args.execpath)
        elif key == 'mode':
            if val == 'texmacs':
                retop = 'Thing#{Standard,Print}=m2jkModeTeXmacs;'
            elif val == 'default' or val == 'pretty':
                retop = 'Thing#{Standard,Print}=m2jkModeStandard;'
        elif key == 'tb':
            retop = self.process_magic('mode=default')[:-5]
        return retop+'--CMD'

    def process_output(self, lines, xcount):
        """"""
        mode = self.conf.args.mode
        if mode == 'default':
            return None, '\n'.join(lines) 
        elif mode == 'texmacs':
            text = ''.join(lines)
            m = self.patt_texmacs.match(text)
            if m: return {'text/html': m.groups()[0]}, None
            return None, None
        elif mode == 'pretty':
            patt_v = re.compile(r'.*\no\d+ = ', re.DOTALL)
            patt_t = re.compile(r'.*\no\d+\s:\s', re.DOTALL)
            patt_vt = re.compile('(.*)\n\n(.*)', re.DOTALL)

            text = '\n'.join(lines)
            mv = patt_v.match(text)
            mt = patt_t.match(text)

            if not mv:
                return None, (text if not mt else '')

            margin = len(str(xcount))+4
            text = '\n'.join([line[margin:] if len(line)>margin else '' for line in lines])
            mvt = patt_vt.match(text)
            return {'text/html': '<pre>{}</pre><pre style="color: gray">{}</pre>'.format(
                    *(mvt.groups() if mvt else (text, ''))
                )}, None
        return None, None

    def run(self, code):
        """ decouples statements from an M2 code block and returns last output
        """
        self.proc.sendline(code)
        output_lines = []

        while True:
            self.proc.expect(self.patt_consume, timeout=self.conf.args.timeout)
            m = self.proc.match
            if not m: raise RuntimeError("***M2JK: Macaulay2 did not return output as expected")
            xcount = int(m.groups()[1])-1
            EOB = False
            
            if not self.conf.args.tb:
                output_lines = []
            for line in m.groups()[0].splitlines():
                if line.endswith('--EOB'):
                    EOB = True
                    continue
                if line.endswith('--CMD'):
                    continue
                output_lines.append(line)
            if EOB:
                return output_lines, xcount

    def send_stream(self, text, stderr=False):
        """ enqueues a stdout or stderr message for the given cell
        """
        stdfile = 'stderr' if stderr else 'stdout' 
        content = {'name': stdfile, 'text': text+'\n'}
        self.send_response(self.iopub_socket, 'stream', content)

    def mock_execute(self, code):
        """ run a cell programmatically - for debuging or otherwise
        """
        code = self.preprocess(code)
        if not code.rstrip():
            return
        output_lines, xcount = self.run(code)
        return self.process_output(output_lines, xcount)[1]

    def do_execute(self, code, silent, store_history=True, user_expressions=None, allow_stdin=False):
        """ kernel entry point for the execution of each cell
        """
        code = self.preprocess(code)
        # self.send_stream("--->\n"+code+"\n<---")

        if not silent:
            if not code.rstrip():
                return {'status': 'ok',
                        'execution_count': None,
                        'payload': [],
                        'user_expressions': {}}

            output_lines, xcount = self.run(code)
            data, stream = self.process_output(output_lines, xcount)

            if stream:
                stdout_content = {'name': 'stdout', 'text': stream}
                self.send_response(self.iopub_socket, 'stream', stdout_content)

            if data:
                execute_content = {'data': data, 'execution_count': xcount}
                self.send_response(self.iopub_socket, 'execute_result', execute_content)

        return {'status': 'ok',
                'execution_count': xcount,
                'payload': [],
                'user_expressions': {}}
