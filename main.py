#!/usr/bin/python
# -*- coding: utf-8 -*-

# common builtin modules
import os
import enum
import re

# GUI modules
import tkinter as tk
from tkinter import ttk
from tkinter import font
from tkinter import messagebox
from tkinter import filedialog

# 3rd party modules
from PIL import Image
import pystray

# custom defined modules
from PassDB import PassDatabase, KeychainRecord


class MenuId(enum.IntEnum):
    INVALID = -1

    DATABASE_CLOSE = 2

    PASS_INSERT = 0  # 子菜单的索引，从零开始
    PASS_UPDATE = 1
    PASS_DELETE = 2

    PASS_ITEM = 2     # 顶层菜单的索引，从一开始


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
    USR_NUM = 3  # TreeView内置的列名：#1,#2,#3,#4
    PWD_NUM = 4  # TreeView内置的列名：#1,#2,#3,#4


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


class UpdateRecordDlg(ModalDialog):
    def __init__(self, master, *a, **kw):
        self._target: KeychainRecord = kw.pop('target')
        ModalDialog.__init__(self, master, *a, **kw)

    def body(self, master):
        padding = {'padx': 5, 'pady': 5}
        # row #1
        sub = tk.Frame(master)
        sub.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding)
        tk.Label(sub, text='Location:', width=10).pack(side=tk.LEFT, **padding)
        self._var_loc = tk.StringVar(value=self._target.loc)
        tk.Entry(sub, textvariable=self._var_loc) \
            .pack(side=tk.LEFT, fill=tk.X, expand=tk.YES, **padding)
        # row #2
        sub = tk.Frame(master)
        sub.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding)
        tk.Label(sub, text='Username:', width=10).pack(side=tk.LEFT, **padding)
        self._var_usr = tk.StringVar(value=self._target.usr)
        tk.Entry(sub, textvariable=self._var_usr) \
            .pack(side=tk.LEFT, fill=tk.X, expand=tk.YES, **padding)
        # row #3
        sub = tk.Frame(master)
        sub.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding)
        tk.Label(sub, text='Password:', width=10).pack(side=tk.LEFT, **padding)
        self._var_pwd = tk.StringVar(value=self._target.pwd)
        tk.Entry(sub, textvariable=self._var_pwd) \
            .pack(side=tk.LEFT, fill=tk.X, expand=tk.YES, **padding)

    def validate(self):
        loc = self._var_loc.get().strip()
        usr = self._var_usr.get().strip()
        pwd = self._var_pwd.get().strip()
        return all(len(i) > 0 for i in [loc, usr, pwd])

    def apply(self):
        self._target.loc = self._var_loc.get().strip()
        self._target.usr = self._var_usr.get().strip()
        self._target.pwd = self._var_pwd.get().strip()
        self.result = True


class MainApp(tk.Tk):
    TITLE = 'PassStore'
    EVENT_DB_EXIST = '<<DBExist>>'  # sent when database is opened / closed.
    TREEVIEW_MAX = 5

    def __init__(self, *a, **kw):
        tk.Tk.__init__(self, *a, **kw)

        self.init_listeners()
        self.init_menu()
        self.init_querying_area()
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
        padding = {'padx': 5, 'pady': 5}
        # querying methods grouped together
        frame = tk.LabelFrame(self, text='Query')
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=tk.YES, **padding)
        # row #1
        sub = tk.Frame(frame)
        sub.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding)
        tk.Label(sub, text='Location:', width=10).pack(side=tk.LEFT, **padding)
        cb = self.register(self.on_location_changed)
        self._var_loc = tk.StringVar()
        tk.Entry(sub, textvariable=self._var_loc, validate='key', validatecommand=(cb, '%P')) \
            .pack(side=tk.LEFT, fill=tk.X, expand=tk.YES, **padding)
        # row #2
        sub = tk.Frame(frame)
        sub.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding)
        tk.Label(sub, text='Username:', width=10).pack(side=tk.LEFT, **padding)
        cb = self.register(self.on_username_changed)
        self._var_usr = tk.StringVar()
        tk.Entry(sub, textvariable=self._var_usr, validate='key', validatecommand=(cb, '%P')) \
            .pack(side=tk.LEFT, fill=tk.X, expand=tk.YES, **padding)
        # row #3
        sub = tk.Frame(frame)
        sub.pack(side=tk.TOP, fill=tk.X, expand=tk.YES, **padding)
        tk.Label(sub, text='Password:', width=10).pack(side=tk.LEFT, **padding)
        cb = self.register(self.on_password_changed)
        self._var_pwd = tk.StringVar()
        tk.Entry(sub, textvariable=self._var_pwd, validate='key', validatecommand=(cb, '%P')) \
            .pack(side=tk.LEFT, fill=tk.X, expand=tk.YES, **padding)
        # result
        ft = font.Font()
        unit_width = max(ft.measure(d) for d in '0123456789')
        columns = ['id', 'location', 'username', 'password']
        widths = [4, 40, 30, 15]
        tv = ttk.Treeview(self, show='headings', height=MainApp.TREEVIEW_MAX, columns=columns, selectmode=tk.BROWSE)
        tv.pack(side=tk.TOP, **padding)
        for i, col in enumerate(columns):
            tv.column(f'#{i + 1}', width=widths[i] * unit_width, anchor=tk.W)
            tv.heading(f'#{i + 1}', text=col)
        tv.bind('<Double-1>', self.on_treeview_click)
        self._tv = tv

    def init_misc(self):
        self.title(MainApp.TITLE)
        self.protocol('WM_DELETE_WINDOW', self.hide_to_systray)
        self.event_generate(MainApp.EVENT_DB_EXIST, state=0)
        self._db = None       # PassDatabase
        self._records = []  # 数据库所有记录一次性读取出来
        self._hits = []   # 搜索的结果，缓存到这里

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
        self.on_input_changed(text, self._var_usr.get().strip(), self._var_pwd.get().strip())
        return True

    def on_username_changed(self, text: str):
        self.on_input_changed(self._var_loc.get().strip(), text, self._var_pwd.get().strip())
        return True

    def on_password_changed(self, text: str):
        self.on_input_changed(self._var_loc.get().strip(), self._var_usr.get().strip(), text)
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
        self.title('[%s] %s' % (MainApp.TITLE, os.path.basename(filename)))

    def menu_database_close(self):
        if self._db is None:
            return
        self._db = None
        self._records.clear()
        self._tv.delete(*self._tv.get_children(''))
        self.event_generate(MainApp.EVENT_DB_EXIST, state=0)

    def quit_app(self):
        if not messagebox.askokcancel(MainApp.TITLE, 'Are you sure to QUIT?'):
            return
        self.menu_database_close()
        self.destroy()

    def menu_insert_pass(self):
        """
        插入一条新记录
        """
        loc = self._var_loc.get().strip()
        usr = self._var_usr.get().strip()
        pwd = self._var_pwd.get().strip()
        if any(len(i) == 0 for i in [loc, usr, pwd]):
            messagebox.showerror(MainApp.TITLE, 'Three fields must not be empty!')
            return
        if any(i.loc == loc and i.usr == usr for i in self._records):
            messagebox.showerror(MainApp.TITLE, 'This location already has this credential!')
            return
        # 1. update database
        new_record = KeychainRecord(loc, usr, pwd)
        self._db.insert(new_record)
        # 2. update model
        self._records.append(new_record)
        # 3. UI is updated automatically by variables' change!
        self._var_loc.set('')
        self._var_usr.set('')
        self._var_pwd.set('')

    def menu_update_pass(self):
        """
        更新当前选中的记录。如果只有一条记录，不用选中
        """
        record_ids = self._tv.get_children('')
        if len(record_ids) == 0:
            messagebox.showerror(MainApp.TITLE, 'No pass item is selected!')
            return
        selected = record_ids[0] if len(record_ids) == 1 else self._tv.focus()
        values = self._tv.item(selected, 'values')
        target: KeychainRecord = self.find_record(sn=int(values[Column.SN]))
        dlg = UpdateRecordDlg(self, target=target)
        if dlg.show() is False:
            return
        # 1. update database
        self._db.update(target)
        # 2. update UI
        self._tv.item(selected, values=(target.sn, target.loc, target.usr, self.pwd_mask(target.pwd)), tags=target.pwd)

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
It's safer to store them to Web browser.

  -- Oct. 13, 2022
  -- Jia Xiao Dong
        '''
        messagebox.showinfo(MainApp.TITLE, msg)

    def restore_from_systray(self, item=None):
        self._icon.stop()
        self.after(0, self.deiconify)

    def hide_to_systray(self):
        icon = Image.new(mode='RGB', size=(32, 32), color='black')
        menu = pystray.MenuItem('default', self.restore_from_systray, enabled=True, default=True, visible=False)
        self._icon = pystray.Icon(name='PassStore', title='PassStore', menu=(menu,), icon=icon)
        self.withdraw()
        self._icon.run()

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
            self._tv.insert('', tk.END, None, values=(h.sn, h.loc, h.usr, self.pwd_mask(h.pwd)), tags=h.pwd)

    def on_treeview_click(self, evt):
        if self._tv.identify_region(evt.x, evt.y) != 'cell':
            return
        record_id = self._tv.identify_row(evt.y)
        if len(record_id) == 0:
            return
        self.clipboard_clear()
        column = self._tv.identify_column(evt.x)
        if column == f'#{Column.PWD_NUM}':
            pwd = self._tv.item(record_id, 'tags')
            self.clipboard_append(pwd)
        elif column == f'#{Column.USR_NUM}':
            values = self._tv.item(record_id, 'values')
            self.clipboard_append(values[Column.USR])
        else:
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
            return '*' * length
        else:
            return '%s%s%s' % (pwd[0], '*' * (length - 2), pwd[-1])


if __name__ == '__main__':
    MainApp().mainloop()
