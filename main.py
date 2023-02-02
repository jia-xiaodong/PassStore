#!/usr/bin/python
# -*- coding: utf-8 -*-

# common builtin modules
import os
import enum
import re
import json

# GUI modules
import tkinter as tk
from tkinter import ttk
from tkinter import font
from tkinter import messagebox
from tkinter import filedialog

# 3rd party modules
from PIL import Image, ImageDraw, ImageFont
import pystray

from otpauth import OtpAuth
# custom defined modules
from PassDB import PassDatabase, KeychainRecord


class MenuId(enum.IntEnum):
    INVALID = -1

    DATABASE_CLOSE = 2

    PASS_INSERT = 0  # 子菜单的索引，从零开始
    PASS_UPDATE = 1
    PASS_DELETE = 2

    PASS_ITEM = 2     # 顶层菜单的索引，从一开始


class OTPType(enum.IntEnum):
    UNKNOWN = -1
    HOTP = 0
    TOTP = 1


class OneTimePass:
    def __init__(self, kind: OTPType, name: str, secret: str, issuer: str):
        self.kind = kind
        self.name = name
        self.secret = secret
        self.issuer = issuer

    @staticmethod
    def from_json(config: str):
        try:
            cfg: dict = json.loads(config)
            k = OneTimePass.type_from_str(cfg.pop('type'))
            n = cfg.pop('name')
            s = cfg.pop('secret')
            i = cfg.pop('issuer')
            return OneTimePass(k, n, s, i)
        except Exception as e:
            return None

    def to_json(self):
        cfg = {'type': self.kind.name.lower(),
               'name': self.name, 'secret': self.secret,
               'issuer': self.issuer}
        return json.dumps(cfg)

    @staticmethod
    def type_from_str(kind: str):
        if kind.lower() == 'totp':
            return OTPType.TOTP
        elif kind.lower() == 'hotp':
            return OTPType.HOTP
        else:
            return OTPType.UNKNOWN


class RelyItem:
    def __init__(self, w, sid: MenuId = MenuId.INVALID):
        """
        @param w is Tkinter widget, could be menu or button
        @note: if w is a menu, then sid is the index of its sub-menu item.
        """
        self._w = w
        self._c = sid

    def set_state(self, state):
        if self._c > MenuId.INVALID:  # menu item
            self._w.entryconfig(int(self._c), state=state)
        else:  # button
            self._w.config(state=state)


class Column(enum.IntEnum):
    SN = 0   #
    LOC = 1  # location
    USR = 2  # username
    PWD = 3  # password
    EXT = 4  # extra
    SN_NUM = 1   # TreeView内置的列名：#1,#2,#3,#4
    LOC_NUM = 2  # 同上
    USR_NUM = 3  # 同上
    PWD_NUM = 4  # 同上
    EXT_NUM = 5  # 同上


class TipEntry(tk.Entry):
    def __init__(self, master, *args, **kwargs):
        self._tip = kwargs.pop('tip', '<placeholder>')
        self._var = kwargs.get('textvariable', None)
        if self._var is None:
            self._var = tk.StringVar()
            self._var.set(self._tip)
            kwargs['textvariable'] = self._var
        tk.Entry.__init__(self, master, *args, **kwargs)
        self.bind('<FocusIn>', self.hide_placeholder_)
        self.bind('<FocusOut>', self.show_placeholder_)

    @property
    def text(self):
        txt = self._var.get().strip()
        return '' if txt == self._tip else txt

    @text.setter
    def text(self, value: str):
        if value is None or len(value) == 0:
            self._var.set(self._tip)
        else:
            self._var.set(value)

    def is_tip(self, text: str):
        return self._tip == text

    def hide_placeholder_(self, evt):
        if self._var.get() == self._tip:
            self.delete(0, tk.END)

    def show_placeholder_(self, evt):
        if len(self._var.get()) == 0:
            self.insert(0, self._tip)


class ModalDialog(tk.Toplevel):
    """
    modal dialog should inherit from this class and override:
    1. body(): required: place your widgets
    2. apply(): required: calculate returning value
    3. buttonbox(): optional: omit it if you like standard buttons (OK and cancel)
    4. validate(): optional: you may need to check if input is valid.

    Dialog support keyword argument: title=...
    Place your widgets on method body()
    Get return value from method apply()
    """
    def __init__(self, parent, *a, **kw):
        title = kw.pop('title', None)

        tk.Toplevel.__init__(self, parent, *a, **kw)
        self.transient(parent)  # when parent minimizes to an icon, it hides too.

        if title:  # dialog title
            self.title(title)

        self.parent = parent
        self.result = None

        body = tk.Frame(self)
        self.initial_focus = self.body(body)
        body.pack(padx=5, pady=5, expand=tk.YES, fill=tk.BOTH)
        self.buttonbox()

        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.geometry("+%d+%d" % (parent.winfo_rootx()+50,
                                  parent.winfo_rooty()+50))

        if not self.initial_focus:
            self.initial_focus = self
        self.initial_focus.focus_set()

        self.lift()
        self.focus_force()
        self.grab_set()
        self.grab_release()

    def show(self):
        """
        enter a local event loop until dialog is destroyed.
        @return False if user cancels the dialog
        """
        self.wait_window(self)
        return self.result is not None

    #
    # construction hooks

    def body(self, master):
        """
        Create dialog body.
        @param master: passed-in argument
        @return widget that should have initial focus.
        @note: must be overridden
        """
        return None

    def buttonbox(self):
        """
        Add standard button box (OK and cancel).
        @note: Override if you don't want the standard buttons
        """
        box = tk.Frame(self)

        w = tk.Button(box, text="OK", width=10, command=self.ok, default=tk.ACTIVE)
        w.pack(side=tk.LEFT, padx=5, pady=5)
        w = tk.Button(box, text="Cancel", width=10, command=self.cancel)
        w.pack(side=tk.LEFT, padx=5, pady=5)

        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

        box.pack()
        return box

    #
    # standard button semantics

    def ok(self, event=None):
        if not self.validate():
            if self.initial_focus:
                self.initial_focus.focus_set()
            return

        self.withdraw()
        self.update_idletasks()

        self.apply()
        self.cancel()

    def cancel(self, event=None):
        self.parent.focus_set()
        self.destroy()

    #
    # command hooks

    def validate(self):
        """
        @note: override if needed
        """
        return True

    def apply(self):
        """
        @note: must be overridden
        """
        pass


class EditRecordDlg(ModalDialog):
    def __init__(self, master, *a, **kw):
        self._target: KeychainRecord = kw.pop('target')
        title = kw.pop('title', None)
        ModalDialog.__init__(self, master, *a, **kw)
        if title is not None:
            self.title(title)

    def body(self, master):
        padding5 = {'padx': 5, 'pady': 5}
        padding0 = {'padx': 0, 'pady': 0}
        frame = tk.LabelFrame(master, text='Basic')
        frame.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding5)
        # row #1
        self._te_loc = TipEntry(frame, tip='<Location>')
        self._te_loc.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding5)
        self._te_loc.text = self._target.loc
        # row #2
        sub = tk.Frame(frame)
        sub.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding0)
        self._te_usr = TipEntry(sub, tip='<Username>')
        self._te_usr.pack(side=tk.LEFT, fill=tk.X, expand=tk.YES, **padding5)
        self._te_usr.text = self._target.usr
        self._te_pwd = TipEntry(sub, tip='<Password>')
        self._te_pwd.pack(side=tk.RIGHT, fill=tk.X, expand=tk.YES, **padding5)
        self._te_pwd.text = self._target.pwd
        #
        otp = OneTimePass.from_json(self._target.ext)
        #
        frame = tk.LabelFrame(master, text='One-Time Password')
        frame.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding5)
        # row 1
        sub = tk.Frame(frame)
        sub.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding5)
        otp_kinds = (OTPType.TOTP.name.lower(), OTPType.HOTP.name.lower())
        self._otp_kind = tk.StringVar(value=otp_kinds[0])
        om = tk.OptionMenu(sub, self._otp_kind, *otp_kinds)
        om.pack(side=tk.LEFT, fill=tk.X, expand=tk.NO, **padding0)
        self._te_otp_name = TipEntry(sub, tip='<Name>')
        self._te_otp_name.pack(side=tk.LEFT, fill=tk.X, expand=tk.YES, **padding0)
        if otp is not None:
            self._te_otp_name.text = otp.name
        self._te_otp_issuer = TipEntry(sub, tip='<Issuer>')
        self._te_otp_issuer.pack(side=tk.RIGHT, fill=tk.X, expand=tk.YES, **padding0)
        if otp is not None:
            self._te_otp_issuer.text = otp.issuer
        # row 2
        self._te_otp_secret = TipEntry(frame, tip='<Secret>')
        self._te_otp_secret.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding5)
        if otp is not None:
            self._te_otp_secret.text = otp.secret

    def validate(self):
        loc = self._te_loc.text
        usr = self._te_usr.text
        pwd = self._te_pwd.text

        otp_valid = False
        if all(len(t) == 0 for t in self.otp_fields):
            otp_valid = True
        elif all(len(t) > 0 for t in self.otp_fields):  # only support TOTP
            otp_valid = self.otp_type == OTPType.TOTP
        return all(len(i) > 0 for i in [loc, usr, pwd]) and otp_valid

    def apply(self):
        self._target.loc = self._te_loc.text
        self._target.usr = self._te_usr.text
        self._target.pwd = self._te_pwd.text
        if all(len(t) > 0 for t in self.otp_fields):
            otp = OneTimePass(self.otp_type, *self.otp_fields)
            self._target.ext = otp.to_json()
        else:
            self._target.ext = ''  # fixme: empty or None?
        self.result = True

    @property
    def otp_type(self):
        return OneTimePass.type_from_str(self._otp_kind.get())

    @property
    def otp_fields(self):
        return [self._te_otp_name.text, self._te_otp_secret.text, self._te_otp_issuer.text]


class MainApp(tk.Tk):
    TITLE = 'PassStore'
    EVENT_DB_EXIST = '<<DBExist>>'  # sent when database is opened / closed.
    TREEVIEW_MAX = 5

    def __init__(self, *a, **kw):
        tk.Tk.__init__(self, *a, **kw)

        self.init_listeners()
        self.init_menu()
        self.init_querying_area()
        self.init_systray_resource()
        self.init_misc()

    def init_menu(self):
        menu_bar = tk.Menu(self)
        #
        menu = tk.Menu(menu_bar, tearoff=0)
        menu.add_command(label='New', command=self.menu_database_new)
        menu.add_command(label='Open', command=self.menu_database_open)
        menu.add_command(label='Close', command=self.menu_database_close)
        self.add_listener(menu, MainApp.EVENT_DB_EXIST, MenuId.DATABASE_CLOSE)
        menu.add_separator()
        menu.add_command(label='Quit', command=self.quit_app)
        menu_bar.add_cascade(label='Database', menu=menu)
        #
        menu = tk.Menu(menu_bar, tearoff=0)
        menu.add_command(label='Insert', command=self.menu_insert_pass)
        self.add_listener(menu, MainApp.EVENT_DB_EXIST, MenuId.PASS_INSERT)
        menu.add_command(label='Update', command=self.menu_update_pass)
        self.add_listener(menu, MainApp.EVENT_DB_EXIST, MenuId.PASS_UPDATE)
        menu.add_command(label='Delete', command=self.menu_delete_pass)
        self.add_listener(menu, MainApp.EVENT_DB_EXIST, MenuId.PASS_DELETE)
        menu_bar.add_cascade(label='PassItem', menu=menu)
        self.add_listener(menu_bar, MainApp.EVENT_DB_EXIST, MenuId.PASS_ITEM)
        #
        menu = tk.Menu(menu_bar, tearoff=0)
        menu.add_command(label='About', command=self.menu_help_about)
        menu_bar.add_cascade(label='Help', menu=menu)
        self.config(menu=menu_bar)

    def init_querying_area(self):
        padding5 = {'padx': 5, 'pady': 5}
        padding0 = {'padx': 0, 'pady': 0}
        # querying methods grouped together
        frame = tk.LabelFrame(self, text='Query')
        frame.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding5)
        # row #1
        self._te_loc = TipEntry(frame, tip='<Location>')
        self._te_loc.pack(side=tk.TOP, fill=tk.X, expand=tk.NO, **padding5)
        # row #2
        sub = tk.Frame(frame)
        sub.pack(side=tk.TOP, fill=tk.X, expand=tk.NO, **padding0)
        self._te_usr = TipEntry(sub, tip='<Username>')
        self._te_usr.pack(side=tk.LEFT, fill=tk.X, expand=tk.YES, **padding5)
        self._te_pwd = TipEntry(sub, tip='<Password>')
        self._te_pwd.pack(side=tk.LEFT, fill=tk.X, expand=tk.YES, **padding5)
        # callback
        cb = self.register(self.on_location_changed)
        self._te_loc.config(validate='key', validatecommand=(cb, '%P'))
        cb = self.register(self.on_username_changed)
        self._te_usr.config(validate='key', validatecommand=(cb, '%P'))
        cb = self.register(self.on_password_changed)
        self._te_pwd.config(validate='key', validatecommand=(cb, '%P'))
        # result
        ft = font.Font()
        unit_width = max(ft.measure(d) for d in '0123456789')
        columns = ['id', 'location', 'username', 'password', 'extra']
        widths = [4, 40, 30, 15, 15]
        tv = ttk.Treeview(self, show='headings', height=MainApp.TREEVIEW_MAX, columns=columns, selectmode=tk.BROWSE)
        tv.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding5)
        for i, col in enumerate(columns):
            tv.column(f'#{i + 1}', width=widths[i] * unit_width, anchor=tk.W)
            tv.heading(f'#{i + 1}', text=col)
        tv.bind('<Double-1>', self.on_treeview_click)
        self._tv = tv
        # add a resize-control
        sub = tk.Frame(self)
        sub.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=tk.NO)
        w = ttk.Sizegrip(sub)
        w.pack(side=tk.RIGHT, fill=tk.BOTH, expand=tk.NO)

    def init_misc(self):
        self.title(MainApp.TITLE)
        self.protocol('WM_DELETE_WINDOW', self.hide_to_systray)
        self.event_generate(MainApp.EVENT_DB_EXIST, state=0)
        self.bind('<Escape>', lambda e: self.hide_to_systray())
        # database
        self._db = None       # PassDatabase
        self._records = []  # 数据库所有记录一次性读取出来

    def init_systray_resource(self):
        self._icon = Image.new(mode='RGB', size=(32, 32), color='black')
        painter = ImageDraw.Draw(self._icon)
        painter.text((5, 5), 'PS', font=ImageFont.truetype('arial.ttf', size=18))
        self._systray_menu = pystray.MenuItem('default', self.restore_from_systray, enabled=True, default=True, visible=False)

    def init_listeners(self):
        self._relied = {}
        self.bind(MainApp.EVENT_DB_EXIST, self.notify_db_event)

    def add_listener(self, wgt, evt, sid: MenuId = MenuId.INVALID):
        """
        @param wgt: widget.
        @param evt: event.
        @param sid: if wgt is a menu, then sid is the index of its sub-menu item. Otherwise it's meaningless.
        """
        item = RelyItem(wgt, sid)
        if evt in self._relied:
            self._relied[evt].append(item)
        else:
            self._relied[evt] = [item]

    def notify_db_event(self, evt):
        state = tk.NORMAL if evt.state else tk.DISABLED
        for w in self._relied[MainApp.EVENT_DB_EXIST]:
            w.set_state(state)

    def on_location_changed(self, text: str):
        if self._te_loc.is_tip(text):
            return True
        self.on_input_changed(text, self._te_usr.text, self._te_pwd.text)
        return True

    def on_username_changed(self, text: str):
        if self._te_usr.is_tip(text):
            return True
        self.on_input_changed(self._te_loc.text, text, self._te_pwd.text)
        return True

    def on_password_changed(self, text: str):
        if self._te_pwd.is_tip(text):
            return True
        self.on_input_changed(self._te_loc.text, self._te_usr.text, text)
        return True

    def on_input_changed(self, loc: str, usr: str, pwd: str):
        hits = list(self._records)
        # 1. location
        if len(loc) != 0:
            pattern = '.*'.join(list(loc))
            regex = re.compile(pattern, re.IGNORECASE)
            hits[:] = [i for i in hits if regex.search(i.loc) is not None]
            if len(hits) == 0:
                self._tv.delete(*self._tv.get_children(''))
                return
        # 2. username
        if len(usr) != 0:
            pattern = '.*'.join(list(usr))
            regex = re.compile(pattern, re.IGNORECASE)
            hits[:] = [i for i in hits if regex.search(i.usr) is not None]
            if len(hits) == 0:
                self._tv.delete(*self._tv.get_children(''))
                return
        # 3. password
        if len(pwd) != 0:
            pattern = '.*'.join(list(pwd))
            regex = re.compile(pattern, re.IGNORECASE)
            hits[:] = [i for i in hits if regex.search(i.pwd) is not None]
        #
        self.refresh_treeview(hits)

    def menu_database_new(self):
        filename = filedialog.asksaveasfilename(defaultextension='.sqlite3')
        if filename == '':
            return
        if os.path.exists(filename):
            messagebox.showinfo(MainApp.TITLE, 'Please delete it in File Explorer')
            return
        self._db = PassDatabase.create_db(filename)
        self._records.clear()
        self.event_generate(MainApp.EVENT_DB_EXIST, state=1)
        self.title('[%s] %s' % (MainApp.TITLE, os.path.basename(filename)))

    def menu_database_open(self):
        option = {'filetypes': [('SQLite3 File', ('*.db3', '*.s3db', '*.sqlite3', '*.sl3')),
                                ('All Files', ('*.*',))]}
        filename = filedialog.askopenfilename(**option)
        if filename == '':
            return
        # if same database, ignore
        if self._db is not None and self._db.source == filename:
            return
        # if unknown database, ignore
        if not PassDatabase.validate(filename):
            messagebox.showerror(MainApp.TITLE, 'Wrong database format')
            return
        if self._db is not None:
            self.menu_database_close()
        self._db = PassDatabase(filename)
        self._records = self._db.select_all()
        self.refresh_treeview(self._records)
        self.event_generate(MainApp.EVENT_DB_EXIST, state=1)
        self.title('[%s] %s (%d entries)' % (MainApp.TITLE, os.path.basename(filename), len(self._records)))

    def menu_database_close(self):
        if self._db is None:
            return
        self._db = None
        self._records.clear()
        self._tv.delete(*self._tv.get_children(''))
        self.event_generate(MainApp.EVENT_DB_EXIST, state=0)
        self.title(MainApp.TITLE)

    def quit_app(self):
        if not messagebox.askokcancel(MainApp.TITLE, 'Are you sure to QUIT?'):
            return
        self.menu_database_close()
        self.destroy()

    def menu_insert_pass(self):
        """
        插入一条新记录
        """
        loc = self._te_loc.text
        usr = self._te_usr.text
        pwd = self._te_pwd.text
        if any(len(i) == 0 for i in [loc, usr, pwd]):
            messagebox.showerror(MainApp.TITLE, 'Three fields must not be empty!')
            return
        if any(i.loc == loc and i.usr == usr for i in self._records):
            messagebox.showerror(MainApp.TITLE, 'This location already has this credential!')
            return
        new_record = KeychainRecord(loc, usr, pwd)
        dlg = EditRecordDlg(self, title='Insert Record', target=new_record)
        if dlg.show() is False:
            return
        # 1. update database
        self._db.insert(new_record)
        # 2. update model
        self._records.append(new_record)
        # 3. UI is updated automatically by variables' change!
        self._te_loc.text = ''
        self._te_usr.text = ''
        self._te_pwd.text = ''

    def menu_update_pass(self):
        """
        更新当前选中的记录。如果只有一条记录，不用选中
        """
        record_ids = self._tv.get_children('')
        if len(record_ids) == 0:
            messagebox.showerror(MainApp.TITLE, 'No pass item is selected!')
            return
        selected = record_ids[0] if len(record_ids) == 1 else self._tv.focus()
        if len(selected) == 0:
            return
        values = self._tv.item(selected, 'values')
        target: KeychainRecord = self.find_record(sn=int(values[Column.SN]))
        dlg = EditRecordDlg(self, title='Update Record', target=target)
        if dlg.show() is False:
            return
        # 1. update database
        self._db.update(target)
        # 2. update UI
        otp = OneTimePass.from_json(target.ext)
        extra = '' if otp is None else otp.kind.name
        self._tv.item(selected, values=(target.sn, target.loc, target.usr, self.pwd_mask(target.pwd), extra), tags=(target.pwd, target.ext))

    def menu_delete_pass(self):
        """
        删除选中的条目
        """
        record_ids = self._tv.get_children('')
        if len(record_ids) == 0:
            return
        # 如果当前只有一条，则无需选中，默认就是选中状态
        selected = record_ids[0] if len(record_ids) == 1 else self._tv.focus()
        values = self._tv.item(selected, 'values')  # tuple
        if not messagebox.askyesno(MainApp.TITLE, f'Are you sure to delete this pass?\nlocation: {values[Column.LOC]}\nusername: {values[Column.USR]}'):
            return
        # 1. update database
        record_id = int(values[Column.SN])
        self._db.delete(record_id)
        # 2. update model
        index = self.find_record_index(sn=record_id)
        self._records.pop(index)
        # 3. update UI
        self._tv.delete(selected)

    def menu_help_about(self):
        msg = '''
Store all credentials together to a local file.
It's safer than storing them to Web browser.

  -- Oct. 13, 2022
  -- Jia Xiao Dong
        '''
        messagebox.showinfo(MainApp.TITLE, msg)

    def restore_from_systray(self, item=None):
        self._systray.stop()
        self.after(0, self.deiconify)

    def hide_to_systray(self):
        self._systray = pystray.Icon(name='PassStore', title='PassStore', menu=(self._systray_menu,), icon=self._icon)
        self.withdraw()
        self._systray.run()

    def on_global_hotkey(self):
        if self.winfo_ismapped():
            self.hide_to_systray()
        else:
            self.restore_from_systray()

    def refresh_treeview(self, hits):
        self._tv.delete(*self._tv.get_children(''))
        for i, h in enumerate(hits):
            if i >= MainApp.TREEVIEW_MAX:
                break
            otp = OneTimePass.from_json(h.ext)
            extra = '' if otp is None else otp.kind.name
            self._tv.insert('', tk.END, None, values=(h.sn, h.loc, h.usr, self.pwd_mask(h.pwd), extra), tags=(h.pwd, h.ext))

    def on_treeview_click(self, evt):
        if self._tv.identify_region(evt.x, evt.y) != 'cell':
            return
        record_id = self._tv.identify_row(evt.y)
        if len(record_id) == 0:
            return
        self.clipboard_clear()
        column = self._tv.identify_column(evt.x)
        if column == f'#{Column.PWD_NUM}':
            pwd, _ = self._tv.item(record_id, 'tags')
            self.clipboard_append(pwd)
        elif column == f'#{Column.USR_NUM}':
            values = self._tv.item(record_id, 'values')
            self.clipboard_append(values[Column.USR])
        elif column == f'#{Column.EXT_NUM}':
            values = self._tv.item(record_id, 'values')
            _, ext = self._tv.item(record_id, 'tags')
            if self.is_otp_type(values[Column.EXT]):  # 当前显示的是OTP类型
                self.show_passcode(record_id, values, ext)
            elif len(values[Column.EXT]) > 0:         # 当前显示的OTP密码
                sep = values[Column.EXT].find(':')
                self.clipboard_append(values[Column.EXT][:sep])
                self.show_passcode(record_id, values, ext, False)
        elif column == f'#{Column.LOC_NUM}':
            values = self._tv.item(record_id, 'values')
            self.clipboard_append(values[Column.LOC])

    def find_record(self, **kw) -> KeychainRecord:
        """
        寻找数据库记录
        :param kw:
        :return:
        """
        target = None
        if 'sn' in kw:
            sn = kw.pop('sn')
            target = next(i for i in self._records if i.sn == sn)
        return target

    def find_record_index(self, **kw) -> int:
        """
        寻找数据库记录
        :param kw:
        :return:
        """
        index = -1
        if 'sn' in kw:
            sn = kw.pop('sn')
            index = next(i for i, j in enumerate(self._records) if j.sn == sn)
        return index

    @staticmethod
    def pwd_mask(pwd: str) -> str:
        length = len(pwd)
        if length < 6:
            if pwd.upper() == 'LDAP':
                return pwd
            return '*' * length
        else:
            return '%s%s%s' % (pwd[0], '*' * (length - 2), pwd[-1])

    @staticmethod
    def is_otp_type(t: str):
        return OneTimePass.type_from_str(t) != OTPType.UNKNOWN

    def show_passcode(self, rid, values, ext, show=True):
        otp = OneTimePass.from_json(ext)
        if show:
            auth = OtpAuth(otp.secret)
            code, remains = auth.totp()
            values = values[:-1]
            self._tv.item(rid, values=(*values, f'{code}:{remains}'))
            self._tv_updater = self.after(1000, lambda: self.update_passcode(rid, values, auth, code, remains))
        else:
            self.after_cancel(self._tv_updater)
            self._tv.item(rid, values=(*values[:-1], otp.kind.name))

    def update_passcode(self, rid, values, otp_auth, code, remains):
        if not self._tv.exists(rid):
            return
        if remains == 0:
            code, remains = otp_auth.totp()
        else:
            remains -= 1
        self._tv.item(rid, values=(*values, f'{code}:{remains}'))
        self._tv_updater = self.after(1000, lambda: self.update_passcode(rid, values, otp_auth, code, remains))


if __name__ == '__main__':
    try:
        root = MainApp()
        root.mainloop()
    except Exception as e:
        print(e)
