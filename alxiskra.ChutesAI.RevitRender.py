# -*- coding: utf-8 -*-
"""
Dynamo Python Node (Revit 2020 / 2022 / 2023+) — Минималистичная студия AI-рендера 3D-видов (v3.8)
через Chutes.ai (Qwen-Image-Edit-2511, Qwen-Image-2512, z-image-turbo, imageclassic)
и совместимые API.

Полная совместимость:
  - Revit 2020 / 2021 (Dynamo 2.x, IronPython 2.7, .NET Framework 4.7.2 / 4.8)
  - Revit 2022+       (Dynamo 2.10+, IronPython 2.7 и CPython 3 / PythonNet)

Изменения и исправления в версии 3.2:
  1. Исправлена ошибка стабильности и «HTTP 500: No infrastructure available to serve request»:
     - Возвращён правильный расчёт пропорций в режиме «Авто Width (по кадру)» (ограничение по БОЛЬШЕЙ
       стороне, как в v3.0): теперь при значении 1024 или 1152 широкий 3D-вид Revit получает размер
       1024x448 / 1152x512 вместо 2048x832 (размер 2048px перегружал видеопамять воркеров Chutes.ai
       и вызывал отказ «No infrastructure available to serve request»).
     - Убран автоматический повтор запросов (Auto-Retry): запрос отправляется один раз без лишних ожиданий.
     - Исправлена ошибка «HTTP 400: Invalid input parameters» при выборе моделей imageclassic,
       Qwen-Image-2512 и z-image-turbo, а также на широких 3D-видах (минимальная сторона >= 512 px).
     - Добавлена автоматическая оптимизация входной картинки в памяти под целевое разрешение перед
       кодированием в Base64 (ускоряет отправку по сети в 3–5 раз).
  2. Исправлен каталог моделей Chutes.ai: убраны устаревшие модели (Qwen-Image-Edit-2509 и FLUX.1-dev),
     оставлены только реально действующие на Chutes.ai модели генерации/редактирования изображений
     (Qwen-Image-Edit-2511, Qwen-Image-2512, z-image-turbo, imageclassic) + возможность добавлять свои.
  3. Исправлено отображение спецсимволов на кнопках в WinForms Revit (убраны квадратики «□» от эмодзи).
  4. Сохранены все функции v3.1: мгновенное открытие без «Печати листа», окно негативного промпта,
     системный промпт, шаблоны промптов, ползунки + ручной ввод для Edit Guidance, Steps и Seed,
     переключатель ручного/автоматического задания Width и Height.

Необязательные входы нода Dynamo (все параметры можно задать прямо в UI):
    IN[0] (str)  : API Key по умолчанию (сохраняется в профиле UI)
    IN[1] (var)  : Кадр 1 по умолчанию (3D-вид из Dynamo, имя вида или путь к файлу)
    IN[2] (str)  : Промпт по умолчанию
    IN[3] (str)  : Base URL по умолчанию ("https://api.chutes.ai")
    IN[4] (str)  : Папка сохранения рендеров (Рабочий стол/Chutes_Renders)
    IN[5] (int)  : Макс. сторона / базовый размер в пикселях (1024)
    IN[6] (int)  : Шаги генерации steps (4)
    IN[7] (var)  : Кадр 2 по умолчанию (необязательно: вид Revit, имя вида или путь к файлу)
    IN[8] (var)  : Кадр 3 по умолчанию (необязательно: вид Revit, имя вида или путь к файлу)
"""

import sys
import os
import time
import json
import base64
import random
import ctypes
import clr

clr.AddReference("System")
clr.AddReference("System.Net")
clr.AddReference("System.Drawing")
clr.AddReference("System.Windows.Forms")
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("RevitServices")

from System import AppDomain, Uri, Enum, Convert, Environment, Array, Byte, IntPtr, EventHandler, Decimal
from System.Collections.Generic import List
from System.Diagnostics import Process, ProcessStartInfo
from System.Net import (
    ServicePointManager,
    SecurityProtocolType,
    HttpWebRequest,
    WebRequest,
    WebProxy,
    CredentialCache,
    WebException,
)
from System.Net.Security import RemoteCertificateValidationCallback
from System.IO import StreamReader, MemoryStream, File, Directory, Path
from System.Text import Encoding
from System.Threading import Thread, ThreadStart
from System.Drawing import (
    Image,
    Bitmap,
    Graphics,
    Pen,
    SolidBrush,
    Rectangle,
    Size,
    Point,
    Font,
    FontStyle,
    Color,
    ContentAlignment,
)
from System.Drawing.Imaging import ImageFormat
from System.Drawing.Drawing2D import SmoothingMode, InterpolationMode
from System.Drawing.Text import TextRenderingHint
from System.Windows.Forms import (
    Application,
    Form,
    Panel,
    PictureBox,
    PictureBoxSizeMode,
    Label,
    Button,
    TextBox,
    ComboBox,
    ComboBoxStyle,
    DrawMode,
    DrawItemState,
    TextRenderer,
    TextFormatFlags,
    AutoScaleMode,
    ListBox,
    CheckBox,
    NumericUpDown,
    TrackBar,
    TickStyle,
    ProgressBar,
    ProgressBarStyle,
    FormBorderStyle,
    FormStartPosition,
    FlatStyle,
    BorderStyle,
    ScrollBars,
    DialogResult,
    MessageBox,
    MessageBoxButtons,
    MessageBoxIcon,
    OpenFileDialog,
    FolderBrowserDialog,
    Cursors,
    MouseButtons,
    ToolTip,
    Clipboard,
    ContextMenu,
    MenuItem,
    Keys,
    Padding,
    Timer,
)

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    View,
    View3D,
    ViewType,
    ImageExportOptions,
    ExportRange,
    FitDirectionType,
    ImageFileType,
    ImageResolution,
    ZoomFitType,
    ElementId,
)
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.UI.Events import IdlingEventArgs
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager


# ==============================================================================
# 1. СОВМЕСТИМОСТЬ IRONPYTHON 2.7 (REVIT 2020/2022) И CPYTHON 3 (REVIT 2022+)
# ==============================================================================

try:
    STRING_TYPES = (str, unicode)

    def u_str(val):
        if val is None:
            return u""
        if isinstance(val, unicode):
            return val
        try:
            return unicode(val)
        except Exception:
            try:
                return unicode(str(val), "utf-8", "ignore")
            except Exception:
                return u""
except NameError:
    STRING_TYPES = (str,)

    def u_str(val):
        return "" if val is None else str(val)


def get_element_id_int(el_id):
    """Безопасное получение числового ID элемента для Revit 2020..2025."""
    if el_id is None:
        return -1
    try:
        return int(el_id.IntegerValue)
    except Exception:
        try:
            return int(el_id.Value)
        except Exception:
            return -1


def to_decimal(val):
    """Безопасное преобразование int/float в System.Decimal для IronPython 2.7 и CPython 3 (PythonNet)."""
    try:
        return Convert.ToDecimal(float(val))
    except Exception:
        try:
            scaled = int(round(abs(float(val)) * 100.0))
            is_neg = bool(float(val) < 0)
            return Decimal(scaled, 0, 0, is_neg, Byte(2))
        except Exception:
            try:
                return Decimal(int(round(float(val))))
            except Exception:
                return Decimal(1)


def from_decimal_float(dec_val, default_val=1.0):
    """Безопасное чтение float из NumericUpDown.Value (System.Decimal) в IronPython и PythonNet."""
    try:
        return float(Convert.ToDouble(dec_val))
    except Exception:
        try:
            return float(u_str(dec_val).replace(u",", u"."))
        except Exception:
            return float(default_val)


def from_decimal_int(dec_val, default_val=1):
    """Безопасное чтение int из NumericUpDown.Value (System.Decimal) в IronPython и PythonNet."""
    try:
        return int(Convert.ToInt32(dec_val))
    except Exception:
        try:
            return int(round(from_decimal_float(dec_val, default_val)))
        except Exception:
            return int(default_val)


def configure_network_tls():
    """
    Настраивает стабильный стек TLS 1.2 / 1.1 / 1.0 (как в рабочей версии v3.0) для .NET Framework 4.7.2 / 4.8.
    Не включает экспериментальный флаг Tls13 (12288), который в .NET 4.8 конфликтует с Schannel.
    """
    try:
        ServicePointManager.SecurityProtocol = (
            SecurityProtocolType.Tls12 | SecurityProtocolType.Tls11 | SecurityProtocolType.Tls
        )
    except Exception:
        try:
            ServicePointManager.SecurityProtocol = Enum.ToObject(SecurityProtocolType, 3072 | 768 | 192)
        except Exception:
            try:
                ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
            except Exception:
                pass
    try:
        ServicePointManager.Expect100Continue = False
        ServicePointManager.DefaultConnectionLimit = 50
        ServicePointManager.UseNagleAlgorithm = False
    except Exception:
        pass
    try:
        ServicePointManager.ServerCertificateValidationCallback = RemoteCertificateValidationCallback(
            lambda sender, cert, chain, ssl_errors: True
        )
    except Exception:
        pass


def paste_into_textbox(tb):
    """
    Надёжная вставка текста из буфера обмена в TextBox внутри немодального окна Revit (form.Show()).
    Использует нативный метод tb.Paste() / Win32 WM_PASTE (0x0302) и резерв через Clipboard.GetText().
    """
    if tb is None:
        return False
    try:
        if tb.ReadOnly:
            return False
    except Exception:
        pass

    try:
        tb.Focus()
    except Exception:
        pass

    try:
        before_text = u_str(tb.Text)
        before_sel = int(tb.SelectionStart)
        tb.Paste()
        if u_str(tb.Text) != before_text or int(tb.SelectionStart) != before_sel:
            return True
    except Exception:
        pass

    try:
        if tb.IsHandleCreated:
            before_text = u_str(tb.Text)
            ctypes.windll.user32.SendMessageW(int(tb.Handle.ToInt64()), 0x0302, 0, 0)
            if u_str(tb.Text) != before_text:
                return True
    except Exception:
        pass

    try:
        if Clipboard.ContainsText():
            clip_text = u_str(Clipboard.GetText())
            if clip_text:
                if not tb.Multiline:
                    clip_text = clip_text.replace(u"\r\n", u" ").replace(u"\n", u" ").replace(u"\r", u" ").strip()
                tb.SelectedText = clip_text
                return True
    except Exception:
        pass
    return False


_LAST_CLIPBOARD_SHORTCUT_TS = [0.0]


def copy_from_textbox(tb, copy_all_if_unselected=False):
    if tb is None:
        return False
    try:
        if int(tb.SelectionLength) > 0:
            sel_text = u_str(tb.SelectedText)
            try:
                tb.Copy()
            except Exception:
                pass
            try:
                if tb.IsHandleCreated:
                    ctypes.windll.user32.SendMessageW(int(tb.Handle.ToInt64()), 0x0301, 0, 0)
            except Exception:
                pass
            try:
                if sel_text:
                    Clipboard.SetText(sel_text)
            except Exception:
                pass
            return True
        elif copy_all_if_unselected and u_str(tb.Text):
            Clipboard.SetText(u_str(tb.Text))
            return True
    except Exception:
        pass
    return False


def cut_from_textbox(tb):
    if tb is None:
        return False
    try:
        if not tb.ReadOnly and int(tb.SelectionLength) > 0:
            sel_text = u_str(tb.SelectedText)
            try:
                tb.Cut()
                return True
            except Exception:
                pass
            try:
                if tb.IsHandleCreated:
                    ctypes.windll.user32.SendMessageW(int(tb.Handle.ToInt64()), 0x0300, 0, 0)
                    return True
            except Exception:
                pass
            try:
                if sel_text:
                    Clipboard.SetText(sel_text)
                    tb.SelectedText = u""
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def enable_textbox_clipboard(tb):
    """
    Включает горячие клавиши буфера обмена (Ctrl+V, Shift+Insert, Ctrl+C, Ctrl+X, Ctrl+A, Ctrl+Z)
    и контекстное меню ПКМ для TextBox в немодальном окне WinForms (form.Show()) внутри Revit.
    """
    if tb is None:
        return
    try:
        tb.ShortcutsEnabled = True
    except Exception:
        pass

    def _on_key_down(sender, e):
        try:
            k_code = int(e.KeyCode) & 0xFFFF
            now_ts = time.time()
            # Ctrl+V (86) или Shift+Insert (45)
            if (e.Control and k_code == 86) or (e.Shift and k_code == 45):
                if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                    _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                    paste_into_textbox(sender)
                e.SuppressKeyPress = True
                e.Handled = True
            # Ctrl+C (67) или Ctrl+Insert (45)
            elif e.Control and (k_code == 67 or k_code == 45):
                if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                    _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                    copy_from_textbox(sender, copy_all_if_unselected=False)
                e.SuppressKeyPress = True
                e.Handled = True
            # Ctrl+X (88) или Shift+Delete (46)
            elif (e.Control and k_code == 88) or (e.Shift and k_code == 46):
                if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                    _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                    cut_from_textbox(sender)
                e.SuppressKeyPress = True
                e.Handled = True
            # Ctrl+A (65)
            elif e.Control and k_code == 65:
                if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                    _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                    sender.SelectAll()
                e.SuppressKeyPress = True
                e.Handled = True
            # Ctrl+Z (90)
            elif e.Control and k_code == 90:
                if not sender.ReadOnly:
                    if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                        _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                        sender.Undo()
                    e.SuppressKeyPress = True
                    e.Handled = True
        except Exception:
            pass

    tb.KeyDown += _on_key_down

    try:
        ctx = ContextMenu()
        if not tb.ReadOnly:
            mi_paste = MenuItem(u"Paste (Ctrl+V)")
            mi_paste.Click += lambda s, a: paste_into_textbox(tb)
            ctx.MenuItems.Add(mi_paste)

            mi_cut = MenuItem(u"Cut (Ctrl+X)")
            mi_cut.Click += lambda s, a: cut_from_textbox(tb)
            ctx.MenuItems.Add(mi_cut)

        mi_copy = MenuItem(u"Copy (Ctrl+C)")
        mi_copy.Click += lambda s, a: copy_from_textbox(tb, copy_all_if_unselected=True)
        ctx.MenuItems.Add(mi_copy)

        mi_sel_all = MenuItem(u"Select All (Ctrl+A)")
        mi_sel_all.Click += lambda s, a: tb.SelectAll()
        ctx.MenuItems.Add(mi_sel_all)

        if not tb.ReadOnly:
            mi_clear = MenuItem(u"Clear")
            mi_clear.Click += lambda s, a: setattr(tb, "Text", u"")
            ctx.MenuItems.Add(mi_clear)

        tb.ContextMenu = ctx
    except Exception:
        pass


def paste_into_numeric_updown(num_ctrl):
    """Вставка целого или дробного числа из буфера обмена (Ctrl+V / Shift+Insert) в NumericUpDown."""
    if num_ctrl is None:
        return False
    try:
        if not num_ctrl.Enabled:
            return False
    except Exception:
        pass
    try:
        if Clipboard.ContainsText():
            raw = u_str(Clipboard.GetText()).strip()
            if raw:
                cleaned = u""
                for ch in raw:
                    if ch.isdigit() or ch in (u".", u",", u"-"):
                        cleaned += (u"." if ch == u"," else ch)
                if cleaned:
                    val_f = float(cleaned)
                    min_f = from_decimal_float(num_ctrl.Minimum, 0.0)
                    max_f = from_decimal_float(num_ctrl.Maximum, 2147483647.0)
                    val_f = max(min_f, min(max_f, val_f))
                    if int(num_ctrl.DecimalPlaces) == 0:
                        num_ctrl.Value = to_decimal(int(round(val_f)))
                    else:
                        num_ctrl.Value = to_decimal(round(val_f, int(num_ctrl.DecimalPlaces)))
                    return True
    except Exception:
        pass
    return False


def copy_from_numeric_updown(num_ctrl):
    """Копирование текущего значения из NumericUpDown в буфер обмена (Ctrl+C)."""
    if num_ctrl is None:
        return False
    try:
        if int(num_ctrl.DecimalPlaces) == 0:
            val_str = u_str(from_decimal_int(num_ctrl.Value, 0))
        else:
            val_str = u_str(from_decimal_float(num_ctrl.Value, 0.0))
        if val_str:
            Clipboard.SetText(val_str)
            return True
    except Exception:
        pass
    return False


def enable_numeric_clipboard(num_ctrl):
    """Включает Ctrl+V / Shift+Insert и Ctrl+C для NumericUpDown (например, поля Seed) в Revit."""
    if num_ctrl is None:
        return

    def _on_num_key_down(sender, e):
        try:
            k_code = int(e.KeyCode) & 0xFFFF
            now_ts = time.time()
            if (e.Control and k_code == 86) or (e.Shift and k_code == 45):
                if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                    _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                    paste_into_numeric_updown(sender)
                e.SuppressKeyPress = True
                e.Handled = True
            elif e.Control and (k_code == 67 or k_code == 45):
                if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                    _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                    copy_from_numeric_updown(sender)
                e.SuppressKeyPress = True
                e.Handled = True
        except Exception:
            pass

    num_ctrl.KeyDown += _on_num_key_down


configure_network_tls()


def get_live_system_proxy():
    """
    Читает актуальные настройки системного прокси Windows напрямую из реестра WinINet,
    чтобы не зависеть от закэшированного при старте Revit состояния прокси/VPN.
    """
    try:
        from Microsoft.Win32 import Registry
        reg_key = Registry.CurrentUser.OpenSubKey(
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        )
        if reg_key is not None:
            proxy_enable = reg_key.GetValue("ProxyEnable", 0)
            proxy_server = u_str(reg_key.GetValue("ProxyServer", u"")).strip()
            reg_key.Close()
            if int(proxy_enable) == 1 and proxy_server:
                target_addr = proxy_server
                if u";" in target_addr or u"=" in target_addr:
                    parts = target_addr.split(u";")
                    picked = u""
                    for p in parts:
                        p_clean = p.strip()
                        if p_clean.lower().startswith(u"https="):
                            picked = p_clean.split(u"=", 1)[1].strip()
                            break
                        elif p_clean.lower().startswith(u"http=") and not picked:
                            picked = p_clean.split(u"=", 1)[1].strip()
                    if picked:
                        target_addr = picked
                if target_addr and not target_addr.lower().startswith(u"http"):
                    target_addr = u"http://" + target_addr
                if target_addr.lower().startswith(u"http://") or target_addr.lower().startswith(u"https://"):
                    wp = WebProxy(Uri(target_addr))
                    wp.Credentials = CredentialCache.DefaultCredentials
                    return wp
            elif int(proxy_enable) == 0:
                return None
    except Exception:
        pass
    try:
        sys_p = WebRequest.GetSystemWebProxy()
        if sys_p is not None:
            sys_p.Credentials = CredentialCache.DefaultCredentials
        return sys_p
    except Exception:
        return None


def get_proxy_candidates_for_url(url):
    live_proxy = get_live_system_proxy()
    if live_proxy is not None:
        return [
            ("sys_proxy", live_proxy),
            ("direct", None),
        ]
    return [
        ("direct", None),
        ("default_proxy", "default"),
    ]


def apply_proxy_mode(req, mode_tuple):
    mode_name, proxy_obj = mode_tuple
    try:
        if mode_name == "direct":
            req.Proxy = None
        elif mode_name == "sys_proxy" and proxy_obj is not None:
            req.Proxy = proxy_obj
        elif mode_name == "default_proxy":
            p = WebRequest.GetSystemWebProxy()
            if p is not None:
                p.Credentials = CredentialCache.DefaultCredentials
                req.Proxy = p
    except Exception:
        pass


def reset_service_point(url):
    try:
        sp = ServicePointManager.FindServicePoint(Uri(url))
        if sp is not None:
            sp.CloseConnectionGroup("")
    except Exception:
        pass


def open_url_in_browser(url):
    """Безопасное открытие ссылки в браузере по умолчанию (IronPython 2.7 и CPython 3)."""
    clean_url = u_str(url).strip()
    if not clean_url:
        return False
    try:
        psi = ProcessStartInfo(clean_url)
        psi.UseShellExecute = True
        Process.Start(psi)
        return True
    except Exception:
        try:
            Process.Start(clean_url)
            return True
        except Exception:
            try:
                psi2 = ProcessStartInfo("cmd.exe", u'/c start "" "{}"'.format(clean_url))
                psi2.UseShellExecute = False
                psi2.CreateNoWindow = True
                Process.Start(psi2)
                return True
            except Exception:
                return False


def open_folder_in_explorer(folder_path):
    """Открывает указанную папку в Проводнике Windows (создаёт папку, если она ещё не существует)."""
    clean_dir = u_str(folder_path).strip()
    if not clean_dir:
        desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop)
        clean_dir = Path.Combine(desktop, u"Chutes_Renders")
    try:
        if not Directory.Exists(clean_dir):
            Directory.CreateDirectory(clean_dir)
    except Exception:
        pass
    try:
        psi = ProcessStartInfo("explorer.exe", u'"{}"'.format(clean_dir))
        psi.UseShellExecute = True
        Process.Start(psi)
        return True
    except Exception:
        try:
            Process.Start("explorer.exe", clean_dir)
            return True
        except Exception:
            return open_url_in_browser(clean_dir)


def get_input(index, default_val=None):
    """Безопасное чтение входных портов Dynamo."""
    try:
        if "IN" in globals() and len(IN) > index and IN[index] is not None:
            val = IN[index]
            if isinstance(val, STRING_TYPES):
                val_clean = u_str(val).strip()
                return val_clean if val_clean != u"" else default_val
            return val
    except Exception:
        pass
    return default_val


def load_image_unlocked(file_path):
    """Загружает System.Drawing.Image в память без блокировки файла на диске."""
    if not file_path or not File.Exists(file_path):
        return None
    raw_bytes = File.ReadAllBytes(file_path)
    ms = MemoryStream(raw_bytes)
    img = Image.FromStream(ms)
    bmp = Bitmap(img)
    img.Dispose()
    ms.Close()
    return bmp


def file_to_base64_str(file_path, max_side_limit=2048):
    """
    Чтение файла изображения в Base64 строку (прямое чтение байтов как в v3.0,
    а уменьшение в памяти — только если внешний файл превышает 2048 px или 4 МБ).
    """
    try:
        raw_bytes_direct = File.ReadAllBytes(file_path)
        if len(raw_bytes_direct) <= 3500000:
            return u_str(Convert.ToBase64String(raw_bytes_direct))
    except Exception:
        pass

    try:
        bmp = load_image_unlocked(file_path)
        if bmp is not None:
            w, h = bmp.Width, bmp.Height
            if max(w, h) > max_side_limit and w > 0 and h > 0:
                scale = float(max_side_limit) / float(max(w, h))
                nw = max(64, int(round(w * scale)))
                nh = max(64, int(round(h * scale)))
                scaled = Bitmap(nw, nh)
                g = Graphics.FromImage(scaled)
                try:
                    g.InterpolationMode = InterpolationMode.HighQualityBicubic
                    g.SmoothingMode = SmoothingMode.AntiAlias
                    g.DrawImage(bmp, Rectangle(0, 0, nw, nh))
                finally:
                    g.Dispose()
                bmp.Dispose()
                ms = MemoryStream()
                scaled.Save(ms, ImageFormat.Png)
                scaled.Dispose()
                b_arr = ms.ToArray()
                ms.Close()
                return u_str(Convert.ToBase64String(b_arr))
            bmp.Dispose()
    except Exception:
        pass

    try:
        raw_bytes = File.ReadAllBytes(file_path)
        return u_str(Convert.ToBase64String(raw_bytes))
    except Exception:
        with open(file_path, "rb") as f:
            raw = f.read()
        b64 = base64.b64encode(raw)
        if not isinstance(b64, str):
            b64 = b64.decode("ascii")
        return u_str(b64)


def write_bytes_to_file(file_path, byte_data):
    """Безопасная запись массива Byte[] или Python bytes в файл."""
    try:
        File.WriteAllBytes(file_path, byte_data)
    except Exception:
        with open(file_path, "wb") as f:
            f.write(bytes(bytearray(byte_data)))


def read_stream_to_bytes(stream):
    """Безопасное чтение потока .NET в массив Byte[] для IronPython 2.7 и CPython 3."""
    mem = MemoryStream()
    buf = Array.CreateInstance(Byte, 8192)
    while True:
        read_count = stream.Read(buf, 0, buf.Length)
        if read_count <= 0:
            break
        mem.Write(buf, 0, read_count)
    data = mem.ToArray()
    mem.Close()
    return data


# ==============================================================================
# 2. МОСТ К REVIT API ДЛЯ НЕМОДАЛЬНОГО ОКНА (РАБОТА ПАРАЛЛЕЛЬНО С REVIT)
# ==============================================================================


def wake_revit_main_window(uiapp):
    """Отправляет пустое сообщение окну Revit, чтобы мгновенно разбудить очередь ExternalEvent/Idling."""
    try:
        hwnd = IntPtr.Zero
        try:
            hwnd = uiapp.MainWindowHandle
        except Exception:
            pass
        h_int = int(hwnd.ToInt64()) if hwnd != IntPtr.Zero else 0
        if h_int != 0:
            ctypes.windll.user32.PostMessageW(h_int, 0x0000, 0, 0)
    except Exception:
        pass


class RevitApiInvoker(object):
    """Позволяет вызывать методы Revit API из немодального окна form.Show()."""

    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.pending_fn = None
        self.result_val = None
        self.error_val = None
        self.is_done = True
        self.ext_event = None
        self.handler = None

        try:
            class _BridgeHandler(IExternalEventHandler):
                __namespace__ = "DynamoChutesAI_" + str(int(time.time() * 1000))

                def __init__(self, parent_invoker):
                    self.parent = parent_invoker

                def Execute(self, app):
                    self.parent._execute_pending(app)

                def GetName(self):
                    return "DynamoChutesAI External Event v3.2"

            self.handler = _BridgeHandler(self)
            self.ext_event = ExternalEvent.Create(self.handler)
        except Exception:
            self.ext_event = None

    def _execute_pending(self, uiapp_arg=None):
        fn = self.pending_fn
        self.pending_fn = None
        if fn is None:
            self.is_done = True
            return
        try:
            self.result_val = fn()
            self.error_val = None
        except Exception as ex:
            self.result_val = None
            self.error_val = ex
        finally:
            self.is_done = True

    def _on_idling(self, sender, args):
        try:
            if self.uiapp is not None:
                self.uiapp.Idling -= self._idling_delegate
        except Exception:
            pass
        self._execute_pending(sender)

    def run(self, fn, force_direct=False):
        """Выполняет функцию fn() в контексте Revit API и возвращает результат."""
        try:
            return fn()
        except Exception as direct_ex:
            if force_direct or self.uiapp is None:
                raise direct_ex

        self.pending_fn = fn
        self.result_val = None
        self.error_val = None
        self.is_done = False

        dispatched = False
        if self.ext_event is not None:
            try:
                self.ext_event.Raise()
                dispatched = True
            except Exception:
                dispatched = False

        if not dispatched:
            try:
                self._idling_delegate = EventHandler[IdlingEventArgs](self._on_idling)
                self.uiapp.Idling += self._idling_delegate
                dispatched = True
            except Exception as idl_ex:
                self.is_done = True
                raise idl_ex

        wake_revit_main_window(self.uiapp)

        t0 = time.time()
        while not self.is_done and (time.time() - t0) < 10.0:
            Application.DoEvents()
            Thread.Sleep(25)
            wake_revit_main_window(self.uiapp)

        if not self.is_done:
            try:
                if hasattr(self, "_idling_delegate") and self.uiapp is not None:
                    self.uiapp.Idling -= self._idling_delegate
            except Exception:
                pass
            raise Exception(u"Операция Revit API недоступна (завершите активную команду в Revit и повторите).")

        if self.error_val is not None:
            raise self.error_val
        return self.result_val


# ==============================================================================
# 3. МЕНЕДЖЕР ПРОФИЛЕЙ, МОДЕЛЕЙ, СИСТЕМНОГО ПРОМПТА И ШАБЛОНОВ
# ==============================================================================

DEFAULT_SYSTEM_PROMPT = (
    u"You are an expert architectural visualizer. Strictly preserve the exact 3D CAD building geometry, "
    u"camera angle, perspective lines, and proportions while applying photorealistic materials and lighting."
)

DEFAULT_POS_TEMPLATES = [
    {
        "name": u"Exterior: Sunny Day (Photorealistic)",
        "text": u"Convert this 3D CAD view into a photorealistic architectural render, preserve exact building contours and geometry, glass and concrete facade, natural daylight, clear sky, realistic trees and environment, 8k",
    },
    {
        "name": u"Exterior: Golden Hour / Warm Sunset",
        "text": u"Photorealistic architectural exterior render at golden hour sunset, warm interior lights glowing through windows, preserve exact 3D geometry and perspective, wet pavement reflections, atmospheric lighting",
    },
    {
        "name": u"Exterior: Overcast / Soft Diffused Light",
        "text": u"Photorealistic architectural visualization, overcast soft diffused lighting, minimalist Scandinavian facade materials, natural brick and timber, preserve exact CAD lines and proportions",
    },
    {
        "name": u"Interior: Modern Minimalist",
        "text": u"Photorealistic modern interior design render, natural oak flooring, soft daylight from windows, realistic textures and furniture materials, strictly preserve room geometry and perspective",
    },
    {
        "name": u"Exterior: Winter Atmosphere",
        "text": u"Photorealistic winter architectural render, fresh snow on ground and trees, crisp cold morning light, warm cozy interior lighting, preserve exact building geometry",
    },
]

DEFAULT_NEG_TEMPLATES = [
    {
        "name": u"Architectural Standard (Anti-Distortion)",
        "text": u"low quality, blurry, distorted geometry, warped perspective, bent lines, deformed building, watermark, text, signature, oversaturated, cartoon, sketch",
    },
    {
        "name": u"Clean Architecture (No People or Cars)",
        "text": u"people, crowds, pedestrians, cars, vehicles, traffic signs, trash, wires, blurry, low resolution, distorted geometry, watermark",
    },
    {
        "name": u"Clean Interior (No Clutter)",
        "text": u"clutter, messy objects, deformed furniture, crooked walls, bad perspective, blurry textures, overexposed, dark shadows, watermark, text",
    },
]


def get_profiles_file_path():
    """Возвращает путь к JSON-файлу профилей в %APPDATA%\\DynamoChutesAI."""
    try:
        appdata = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData)
        cfg_dir = Path.Combine(appdata, u"DynamoChutesAI")
        if not Directory.Exists(cfg_dir):
            Directory.CreateDirectory(cfg_dir)
        return Path.Combine(cfg_dir, u"profiles.json")
    except Exception:
        desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop)
        return Path.Combine(desktop, u"dynamo_chutes_profiles.json")


def _ensure_profile_defaults(data_dict):
    """Гарантирует наличие полей шаблонов, системного промпта и пользовательских моделей."""
    if not isinstance(data_dict, dict):
        data_dict = {}
    if "profiles" not in data_dict or not isinstance(data_dict["profiles"], dict) or len(data_dict["profiles"]) == 0:
        data_dict["profiles"] = {
            u"Chutes.ai": {
                "base_url": u"https://api.chutes.ai",
                "api_key": u"",
                "last_model": u"Qwen-Image-Edit-2511",
                "custom_models": [],
            }
        }
    elif u"Chutes.ai (Основной)" in data_dict["profiles"]:
        old_prof_val = data_dict["profiles"].pop(u"Chutes.ai (Основной)")
        if u"Chutes.ai" not in data_dict["profiles"]:
            data_dict["profiles"][u"Chutes.ai"] = old_prof_val
        if data_dict.get("active_profile") == u"Chutes.ai (Основной)":
            data_dict["active_profile"] = u"Chutes.ai"
    if "active_profile" not in data_dict or data_dict["active_profile"] not in data_dict["profiles"]:
        data_dict["active_profile"] = sorted(data_dict["profiles"].keys())[0]

    for p_key, p_val in data_dict["profiles"].items():
        if isinstance(p_val, dict):
            if "custom_models" not in p_val or not isinstance(p_val["custom_models"], list):
                p_val["custom_models"] = []

    if "system_prompt" not in data_dict:
        data_dict["system_prompt"] = DEFAULT_SYSTEM_PROMPT
    if "use_system_prompt" not in data_dict:
        data_dict["use_system_prompt"] = False
    if "ui_dark_mode" not in data_dict:
        data_dict["ui_dark_mode"] = False
    if "prompt_templates" not in data_dict or not isinstance(data_dict["prompt_templates"], list) or len(data_dict["prompt_templates"]) == 0:
        data_dict["prompt_templates"] = list(DEFAULT_POS_TEMPLATES)
    if "neg_prompt_templates" not in data_dict or not isinstance(data_dict["neg_prompt_templates"], list) or len(data_dict["neg_prompt_templates"]) == 0:
        data_dict["neg_prompt_templates"] = list(DEFAULT_NEG_TEMPLATES)
    return data_dict


def load_profiles_data():
    """Загружает сохранённые профили, шаблоны и системный промпт из JSON."""
    cfg_path = get_profiles_file_path()
    if File.Exists(cfg_path):
        try:
            raw_text = File.ReadAllText(cfg_path, Encoding.UTF8)
            parsed = json.loads(u_str(raw_text))
            if isinstance(parsed, dict):
                return _ensure_profile_defaults(parsed)
        except Exception:
            pass
    return _ensure_profile_defaults({})


def save_profiles_data(data_dict):
    """Сохраняет словарь профилей и шаблонов в JSON."""
    cfg_path = get_profiles_file_path()
    try:
        json_str = json.dumps(data_dict, ensure_ascii=False, indent=2)
        File.WriteAllText(cfg_path, u_str(json_str), Encoding.UTF8)
        return True
    except Exception:
        try:
            json_str = json.dumps(data_dict, ensure_ascii=True, indent=2)
            File.WriteAllText(cfg_path, u_str(json_str), Encoding.UTF8)
            return True
        except Exception:
            return False


# ==============================================================================
# 4. АКТУАЛЬНЫЙ КАТАЛОГ МОДЕЛЕЙ CHUTES.AI И ПОЛЬЗОВАТЕЛЬСКИЕ МОДЕЛИ
# ==============================================================================

# Только реально работающие на Chutes.ai модели генерации/редактирования изображений
# (устаревшие Qwen-Image-Edit-2509 и FLUX.1-dev удалены)
BUILTIN_CHUTES_IMAGE_MODELS = [
    {
        "id": u"Qwen-Image-Edit-2511",
        "title": u"Qwen-Image-Edit-2511",
        "slug": u"vonkaiser-qwen-image-edit-2511",
        "endpoint": u"https://vonkaiser-qwen-image-edit-2511.chutes.ai/generate",
        "mode": u"img2img_qwen",
        "owner": u"vonkaiser",
        "description": u"Image-to-Image CAD render & edit using 1..3 input scenes",
        "default_steps": 4,
        "default_guidance": 1.0,
    },
    {
        "id": u"Qwen-Image-2512",
        "title": u"Qwen-Image-2512",
        "slug": u"vonkaiser-qwen-image-2512",
        "endpoint": u"https://vonkaiser-qwen-image-2512.chutes.ai/generate",
        "mode": u"txt2img_chute",
        "owner": u"vonkaiser",
        "description": u"Text-to-Image generation (Qwen-Image-2512)",
        "default_steps": 8,
        "default_guidance": 3.5,
    },
    {
        "id": u"z-image-turbo",
        "title": u"z-image-turbo",
        "slug": u"vonkaiser-z-image-turbo",
        "endpoint": u"https://vonkaiser-z-image-turbo.chutes.ai/generate",
        "mode": u"txt2img_chute",
        "owner": u"vonkaiser",
        "description": u"Fast Text-to-Image generation (Z-Image Turbo)",
        "default_steps": 4,
        "default_guidance": 1.0,
    },
    {
        "id": u"imageclassic",
        "title": u"imageclassic",
        "slug": u"vonkaiser-imageclassic",
        "endpoint": u"https://vonkaiser-imageclassic.chutes.ai/image/juggernaut",
        "mode": u"txt2img_chute",
        "owner": u"vonkaiser",
        "description": u"Classic diffusion pipelines (Juggernaut XL / FLUX.1-schnell / Dreamshaper XL)",
        "default_steps": 20,
        "default_guidance": 5.0,
        "sub_model": u"juggernaut",
    },
]

IMAGE_POSITIVE_KEYWORDS = (
    "image",
    "img",
    "flux",
    "diffusion",
    "sdxl",
    "stable-diffusion",
    "qwen-image",
    "z-image",
    "hidream",
    "hunyuan-image",
    "juggernaut",
    "chroma",
    "illustrij",
    "inpaint",
    "controlnet",
    "dall-e",
    "gpt-image",
    "playground",
    "kandinsky",
    "kolors",
    "recraft",
    "ideogram",
    "imagen",
)

# sam3 — это модель сегментации/масок (Segment Anything 3), а не генератор рендеров,
# поэтому она исключена из автофильтра генераторов (при желании её можно добавить вручную).
IMAGE_NEGATIVE_KEYWORDS = (
    "llm",
    "vllm",
    "sglang",
    "tei",
    "embedding",
    "rerank",
    "whisper",
    "kokoro",
    "tts",
    "audio",
    "music",
    "speech",
    "video",
    "i2v",
    "t2v",
    "sam3",
    "nsfw-classifier",
    "docuextract",
)


def is_image_generation_chute(item_dict):
    if not isinstance(item_dict, dict):
        return False
    template = u_str(item_dict.get("standard_template", "")).lower()
    name = u_str(item_dict.get("name", "") or item_dict.get("id", "")).lower()
    slug = u_str(item_dict.get("slug", "")).lower()
    tagline = u_str(item_dict.get("tagline", "") or item_dict.get("description", "")).lower()
    combined = u"{} {} {} {}".format(template, name, slug, tagline)
    for neg in IMAGE_NEGATIVE_KEYWORDS:
        if neg in name or neg in slug or neg == template:
            return False
    if template == u"diffusion":
        return True
    cords = item_dict.get("cords")
    if isinstance(cords, list):
        for c in cords:
            if isinstance(c, dict):
                p = u_str(c.get("public_api_path", "") or c.get("path", "")).lower()
                out_ct = u_str(c.get("output_content_type", "")).lower()
                if u"image/" in out_ct or p in (u"/generate", u"/img2img", u"/text2image", u"/sdxl", u"/edit"):
                    if not any(neg in combined for neg in IMAGE_NEGATIVE_KEYWORDS):
                        return True
    for pos in IMAGE_POSITIVE_KEYWORDS:
        if pos in combined:
            return True
    return False


def build_custom_model_entry(model_name, base_url, explicit_endpoint=u""):
    """Строит запись модели (для Chutes или любого стороннего провайдера) по введённому имени."""
    clean_name = u_str(model_name).strip()
    clean_base = u_str(base_url).strip().rstrip(u"/") or u"https://api.chutes.ai"
    ep = u_str(explicit_endpoint).strip()

    name_low = clean_name.lower()
    for preset in BUILTIN_CHUTES_IMAGE_MODELS:
        if preset["id"].lower() == name_low or preset["slug"].lower() == name_low:
            entry = dict(preset)
            if ep:
                entry["endpoint"] = ep
            entry["owner"] = u"custom"
            return entry

    is_edit = (u"edit" in name_low) or (u"img2img" in name_low) or (u"control" in name_low)
    if not ep:
        if clean_name.startswith(u"http://") or clean_name.startswith(u"https://"):
            ep = clean_name if clean_name.endswith(u"/generate") else clean_name.rstrip(u"/") + u"/generate"
        elif u"chutes.ai" in clean_base.lower():
            slug_part = clean_name.lower().replace(u" ", u"-").replace(u"/", u"-")
            if u".chutes.ai" in slug_part:
                ep = u"https://" + slug_part.split(u"//")[-1].rstrip(u"/") + u"/generate"
            else:
                ep = u"https://{}.chutes.ai/generate".format(slug_part)
        else:
            if clean_base.endswith(u"/generations") or clean_base.endswith(u"/generate"):
                ep = clean_base
            elif clean_base.endswith(u"/v1"):
                ep = clean_base + u"/images/generations"
            else:
                ep = clean_base + u"/v1/images/generations"

    mode = u"img2img_qwen" if is_edit else (u"txt2img_chute" if u"chutes.ai" in ep.lower() else u"txt2img_unified")
    def_steps = 4 if (is_edit or u"turbo" in name_low or u"schnell" in name_low) else 8
    def_guidance = 1.0 if is_edit else 3.5

    return {
        "id": clean_name,
        "title": clean_name,
        "slug": clean_name,
        "endpoint": ep,
        "mode": mode,
        "owner": u"custom",
        "description": u"Custom model (saved in profile)",
        "default_steps": def_steps,
        "default_guidance": def_guidance,
        "is_custom": True,
    }


def build_chute_endpoint(item_dict, base_url):
    slug = u_str(item_dict.get("slug", "")).strip()
    name = u_str(item_dict.get("name", "") or item_dict.get("id", "")).strip()
    username = u""
    user_obj = item_dict.get("user")
    if isinstance(user_obj, dict):
        username = u_str(user_obj.get("username", "")).strip()
    if not username:
        username = u_str(item_dict.get("username", "")).strip()

    name_low = name.lower()
    slug_low = slug.lower()

    # Для встроенных проверенных моделей Chutes.ai всегда возвращаем их точный публичный эндпоинт
    # (не заменяя его на внутренний cord.path, чтобы не возникала ошибка 404: No matching cord found!)
    for preset in BUILTIN_CHUTES_IMAGE_MODELS:
        if (
            preset["id"].lower() == name_low
            or preset["slug"].lower() == slug_low
            or preset["id"].lower() in slug_low
        ):
            return preset["endpoint"], preset["mode"], preset["default_steps"], preset.get("default_guidance", 1.0)

    cord_path = u"/generate"
    cords = item_dict.get("cords")
    if isinstance(cords, list) and len(cords) > 0:
        for c in cords:
            if isinstance(c, dict):
                # ВАЖНО: берём только public_api_path (а не внутренний path функции контейнера!)
                p = u_str(c.get("public_api_path", "")).strip()
                if p in (u"/generate", u"/image/juggernaut", u"/image/flux", u"/img2img", u"/text2image", u"/edit"):
                    cord_path = p
                    break

    if slug and u"chutes.ai" in base_url.lower():
        host = slug
        if username and not host.lower().startswith(username.lower() + u"-"):
            host = u"{}-{}".format(username, slug)
        endpoint = u"https://{}.chutes.ai{}".format(host.lower(), cord_path)
    elif u"chutes.ai" in base_url.lower():
        clean_slug = name.lower().replace(u" ", u"-").replace(u"_", u"-").replace(u"/", u"-")
        if username:
            endpoint = u"https://{}-{}.chutes.ai{}".format(username.lower(), clean_slug, cord_path)
        else:
            endpoint = u"https://image.chutes.ai/generate"
    else:
        clean_b = base_url.rstrip(u"/")
        if clean_b.endswith(u"/v1"):
            endpoint = clean_b + u"/images/generations"
        else:
            endpoint = clean_b + u"/v1/images/generations"

    is_edit = (u"edit" in name_low) or (u"edit" in slug_low) or (u"img2img" in cord_path)
    mode = u"img2img_qwen" if is_edit else (u"txt2img_chute" if u"chutes.ai" in endpoint.lower() else u"txt2img_unified")
    steps = 4 if (is_edit or u"turbo" in name_low) else 8
    guidance = 1.0 if is_edit else 3.5
    return endpoint, mode, steps, guidance


def curl_get_json_fallback(url, api_key, timeout_sec=12):
    """Резервный GET-запрос через встроенный системный curl.exe Windows 10/11."""
    temp_out = Path.Combine(Path.GetTempPath(), u"chutes_get_{}.json".format(int(time.time() * 1000)))
    for extra_arg in (u"", u'--noproxy "*" '):
        try:
            clean_key = u_str(api_key).replace(u"Bearer ", u"").strip()
            auth_part = u'-H "Authorization: Bearer {}" '.format(clean_key) if clean_key else u""
            args = u'-sS -k {}--max-time {} -H "Accept: application/json" {}-o "{}" -w "%{{http_code}}" "{}"'.format(
                extra_arg, int(timeout_sec), auth_part, temp_out, u_str(url)
            )
            psi = ProcessStartInfo("curl.exe", args)
            psi.UseShellExecute = False
            psi.CreateNoWindow = True
            psi.RedirectStandardOutput = True
            psi.RedirectStandardError = True
            proc = Process.Start(psi)
            stdout_str = proc.StandardOutput.ReadToEnd()
            proc.WaitForExit(int(timeout_sec * 1000 + 3000))
            code_str = u_str(stdout_str).strip()
            http_code = int(code_str) if code_str.isdigit() else -1
            if http_code == 200 and File.Exists(temp_out):
                raw_text = File.ReadAllText(temp_out, Encoding.UTF8)
                try:
                    File.Delete(temp_out)
                except Exception:
                    pass
                return 200, json.loads(u_str(raw_text))
        except Exception:
            pass
    try:
        if File.Exists(temp_out):
            File.Delete(temp_out)
    except Exception:
        pass
    return -1, u"curl fallback failed"


def http_get_json(url, api_key, timeout_ms=12000):
    """Выполняет GET-запрос с автообходом залипшего прокси и резервом через curl.exe."""
    configure_network_tls()
    last_err_code = -1
    last_err_msg = u""

    for proxy_mode in get_proxy_candidates_for_url(url):
        try:
            req = HttpWebRequest.Create(url)
            req.Method = "GET"
            req.Timeout = timeout_ms
            req.ReadWriteTimeout = timeout_ms
            req.KeepAlive = False
            req.Accept = "application/json"
            req.UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DynamoRevitAI/3.2"
            try:
                req.ServicePoint.Expect100Continue = False
            except Exception:
                pass
            apply_proxy_mode(req, proxy_mode)

            if api_key:
                clean_key = u_str(api_key).replace(u"Bearer ", u"").strip()
                if clean_key:
                    req.Headers.Add("Authorization", "Bearer " + clean_key)

            resp = req.GetResponse()
            code = Convert.ToInt32(resp.StatusCode)
            stream = resp.GetResponseStream()
            raw_bytes = read_stream_to_bytes(stream)
            stream.Close()
            resp.Close()

            text = Encoding.UTF8.GetString(raw_bytes)
            return code, json.loads(u_str(text))
        except WebException as wex:
            err_code = -1
            err_msg = u_str(wex.Message)
            if wex.Response is not None:
                try:
                    err_code = Convert.ToInt32(wex.Response.StatusCode)
                    reader = StreamReader(wex.Response.GetResponseStream(), Encoding.UTF8)
                    err_body = reader.ReadToEnd()
                    reader.Close()
                    if err_body:
                        err_msg = u_str(err_body)
                except Exception:
                    pass
                return err_code, err_msg
            last_err_code = err_code
            last_err_msg = err_msg
            reset_service_point(url)
        except Exception as ex:
            last_err_code = -1
            last_err_msg = u_str(ex)

    c_code, c_data = curl_get_json_fallback(url, api_key, timeout_sec=max(6, int(timeout_ms / 1000)))
    if c_code == 200:
        return c_code, c_data

    return last_err_code, last_err_msg


def fetch_provider_image_models(base_url, api_key, custom_models=None, fetch_online=True):
    """
    Собирает список моделей:
      1) Пользовательские модели из активного профиля (custom_models);
      2) При fetch_online=True — запрашивает актуальные модели у провайдера по API (/chutes/ или /v1/models);
      3) Если онлайн-запрос не выполнялся или не вернул моделей — добавляет 4 актуальные модели Chutes.ai.
    """
    clean_base = u_str(base_url).strip().rstrip(u"/")
    if not clean_base:
        clean_base = u"https://api.chutes.ai"

    discovered = []
    seen_ids = set()
    api_notes = []
    online_matched_total = 0

    def add_model_entry(entry):
        if not isinstance(entry, dict):
            return
        mid = u_str(entry.get("id", "")).strip()
        if not mid:
            return
        key_low = mid.lower()
        if key_low in seen_ids:
            return
        seen_ids.add(key_low)
        entry_copy = dict(entry)
        entry_copy["title"] = mid
        if "default_steps" not in entry_copy:
            entry_copy["default_steps"] = 4
        if "default_guidance" not in entry_copy:
            entry_copy["default_guidance"] = 1.0 if entry_copy.get("mode") == u"img2img_qwen" else 3.5
        discovered.append(entry_copy)

    # 1. Пользовательские модели из профиля
    if isinstance(custom_models, list):
        for cm in custom_models:
            if isinstance(cm, dict) and cm.get("id"):
                add_model_entry(cm)
            elif isinstance(cm, STRING_TYPES) and u_str(cm).strip():
                add_model_entry(build_custom_model_entry(cm, clean_base))

    # 2. Если в Base URL указан прямой адрес конкретного chute
    if u".chutes.ai" in clean_base.lower() and not clean_base.lower().startswith(u"https://api.chutes.ai"):
        direct_ep = clean_base if clean_base.endswith(u"/generate") else clean_base + u"/generate"
        host_part = clean_base.split(u"//")[-1].split(u".")[0]
        is_edit = u"edit" in host_part.lower()
        add_model_entry({
            "id": host_part,
            "title": host_part,
            "slug": host_part,
            "endpoint": direct_ep,
            "mode": u"img2img_qwen" if is_edit else u"txt2img_chute",
            "owner": u"custom",
            "description": u"Direct chute endpoint from Base URL",
            "default_steps": 4,
            "default_guidance": 1.0 if is_edit else 3.5,
        })

    # 3. Онлайн-опрос API провайдера
    if fetch_online:
        candidate_urls = []
        is_chutes_host = u"chutes.ai" in clean_base.lower()
        if is_chutes_host:
            candidate_urls.append(u"https://api.chutes.ai/chutes/?include_public=true&limit=200")
            candidate_urls.append(u"https://api.chutes.ai/chutes/?include_public=true&template=diffusion&limit=100")
        else:
            if clean_base.endswith(u"/v1"):
                candidate_urls.append(clean_base + u"/models")
            else:
                candidate_urls.append(clean_base + u"/v1/models")
                candidate_urls.append(clean_base + u"/models")
            candidate_urls.append(clean_base + u"/chutes/?include_public=true&limit=200")

        for url in candidate_urls:
            code, data = http_get_json(url, api_key, timeout_ms=10000)
            if code == 200 and data is not None:
                items = []
                if isinstance(data, dict):
                    items = data.get("items") or data.get("data") or data.get("models") or data.get("chutes") or []
                elif isinstance(data, list):
                    items = data

                matched_count = 0
                fallback_external = []
                for item in items:
                    if isinstance(item, dict):
                        raw_name = u_str(item.get("name") or item.get("id") or item.get("slug") or u"").strip()
                        if not raw_name:
                            continue
                        if is_image_generation_chute(item):
                            ep, mode, def_steps, def_cfg = build_chute_endpoint(item, clean_base)
                            tagline = u_str(item.get("tagline") or item.get("description") or u"").strip()
                            add_model_entry({
                                "id": raw_name,
                                "title": raw_name,
                                "slug": u_str(item.get("slug", raw_name)),
                                "endpoint": ep,
                                "mode": mode,
                                "owner": u_str((item.get("user") or {}).get("username", "")) if isinstance(item.get("user"), dict) else u"",
                                "description": tagline or u"Discovered online via provider API",
                                "default_steps": def_steps,
                                "default_guidance": def_cfg,
                                "cords": item.get("cords") if isinstance(item.get("cords"), list) else [],
                            })
                            matched_count += 1
                        elif not is_chutes_host:
                            low_n = raw_name.lower()
                            if not any(neg in low_n for neg in IMAGE_NEGATIVE_KEYWORDS):
                                fallback_external.append(raw_name)
                    elif isinstance(item, STRING_TYPES) and not is_chutes_host:
                        raw_name = u_str(item).strip()
                        if raw_name:
                            fallback_external.append(raw_name)

                if matched_count == 0 and not is_chutes_host and len(fallback_external) > 0:
                    for ext_name in fallback_external[:100]:
                        add_model_entry(build_custom_model_entry(ext_name, clean_base))
                        matched_count += 1

                online_matched_total += matched_count
                api_notes.append(u"API {}: {}".format(code, matched_count))
                if matched_count > 0:
                    break
            elif code > 0:
                api_notes.append(u"HTTP {}".format(code))

    # Добавляем базовую четвёрку Chutes только если онлайн-запрос не делался (при быстром старте) или ничего не вернул
    if online_matched_total == 0:
        for preset in BUILTIN_CHUTES_IMAGE_MODELS:
            add_model_entry(dict(preset))

    custom_cnt = sum(1 for m in discovered if m.get("owner") == u"custom" or m.get("is_custom"))
    if fetch_online and online_matched_total > 0:
        status_summary = u"Online API + {} Profile".format(custom_cnt) if custom_cnt > 0 else u"Online API"
    elif fetch_online and api_notes:
        status_summary = u"Built-in ({})".format(u", ".join(api_notes))
    else:
        status_summary = u"Built-in + {} Profile".format(custom_cnt) if custom_cnt > 0 else u"Built-in"
    return discovered, status_summary


# ==============================================================================
# 5. РАБОТА С 3D-ВИДАМИ REVIT (ПОИСК, СПИСОК, ПРЯМОЙ ЭКСПОРТ ВИДА В PNG)
# ==============================================================================


def can_export_view(v):
    if v is None:
        return False
    try:
        if v.IsTemplate:
            return False
        return bool(v.CanBePrinted)
    except Exception:
        return False


def collect_project_views(doc, include_non_3d=False):
    result = []
    if doc is None:
        return result

    active_id = -1
    try:
        if doc.ActiveView is not None:
            active_id = get_element_id_int(doc.ActiveView.Id)
    except Exception:
        pass

    collector = FilteredElementCollector(doc).OfClass(View)
    views_3d = []
    views_other = []

    for v in collector:
        if not can_export_view(v):
            continue
        v_name = u_str(v.Name)
        v_id = get_element_id_int(v.Id)
        is_act = (v_id == active_id)
        is_3d = isinstance(v, View3D) or (v.ViewType == ViewType.ThreeD)

        if is_3d:
            prefix = u"★ [Active 3D] " if is_act else u"[3D] "
            views_3d.append({
                "name": v_name,
                "label": prefix + v_name,
                "view": v,
                "is_3d": True,
                "is_active": is_act,
            })
        elif include_non_3d:
            prefix = u"★ [Active] " if is_act else u"[2D] "
            views_other.append({
                "name": v_name,
                "label": prefix + v_name,
                "view": v,
                "is_3d": False,
                "is_active": is_act,
            })

    views_3d.sort(
        key=lambda x: (
            0 if x["is_active"] else (1 if x["name"] == u"{3D}" else 2),
            x["name"].lower(),
        )
    )
    views_other.sort(key=lambda x: (0 if x["is_active"] else 1, x["name"].lower()))
    return views_3d + views_other


def export_revit_view_to_png(doc, target_view, out_dir, pixel_size=1024, file_prefix=u"source_view"):
    """Экспортирует указанный вид Revit в PNG в его собственных настройках графики Revit."""
    if not Directory.Exists(out_dir):
        Directory.CreateDirectory(out_dir)

    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass

    stamp = u_str(int(time.time() * 1000))
    temp_prefix = u"chutes_tmp_" + stamp
    base_filepath = Path.Combine(out_dir, temp_prefix)

    opts = ImageExportOptions()
    opts.ZoomType = ZoomFitType.FitToPage
    opts.PixelSize = int(max(256, min(3072, int(pixel_size))))
    opts.FitDirection = FitDirectionType.Horizontal
    opts.HLRandWFViewsFileType = ImageFileType.PNG
    opts.ShadowViewsFileType = ImageFileType.PNG
    opts.ImageResolution = ImageResolution.DPI_150
    opts.ShouldCreateWebSite = False

    view_ids = List[ElementId]()
    view_ids.Add(target_view.Id)
    opts.SetViewsAndSheets(view_ids)
    opts.ExportRange = ExportRange.SetOfViews
    opts.FilePath = base_filepath

    doc.ExportImage(opts)

    found_files = Directory.GetFiles(out_dir, temp_prefix + u"*.png")
    if not found_files or len(found_files) == 0:
        raise Exception(u"Не удалось экспортировать вид '{}'".format(u_str(target_view.Name)))

    exported_file = found_files[0]
    clean_path = Path.Combine(out_dir, u"{}_{}.png".format(file_prefix, stamp))
    try:
        if File.Exists(clean_path):
            File.Delete(clean_path)
        File.Move(exported_file, clean_path)
        for f in found_files:
            if File.Exists(f) and f != clean_path:
                try:
                    File.Delete(f)
                except Exception:
                    pass
        return clean_path
    except Exception:
        return exported_file


def calc_target_dimensions(image_path, max_side=1024):
    """
    Вычисляет width и height кратно 64 с сохранением пропорций исходного кадра:
    - ограничивает БОЛЬШУЮ сторону значением max_side (чтобы не раздувать кадр до 2048px и не вызывать HTTP 500);
    - гарантирует МЕНЬШУЮ сторону не менее 512px (требование валидации схем Chutes.ai ge=512, чтобы не возникала
      ошибка HTTP 400: Invalid input parameters на широких видах вроде 1024x448 -> выравнивается до 1024x512).
    """
    side_clamped = int(round(float(max_side) / 64.0) * 64)
    side_clamped = max(512, min(2048, side_clamped))
    try:
        img = load_image_unlocked(image_path)
        if img is not None:
            orig_w = img.Width
            orig_h = img.Height
            img.Dispose()
            if orig_w > 0 and orig_h > 0:
                scale = float(side_clamped) / float(max(orig_w, orig_h))
                w = int(round((orig_w * scale) / 64.0) * 64)
                h = int(round((orig_h * scale) / 64.0) * 64)
                w = max(512, min(2048, w))
                h = max(512, min(2048, h))
                return w, h
    except Exception:
        pass
    return side_clamped, side_clamped


# ==============================================================================
# 6. ФОРМИРОВАНИЕ ПАКЕТА И ОТПРАВКА ЗАПРОСА НА ГЕНЕРАЦИЮ (БЕЗ АВТО-ПОВТОРОВ)
# ==============================================================================


def is_model_img2img(model_info, endpoint_url=u""):
    """
    Возвращает True, если выбранная модель поддерживает редактирование входных кадров (image_b64s),
    например Qwen-Image-Edit-2511. Для чисто текстовых моделей Chutes.ai
    (imageclassic, Qwen-Image-2512, z-image-turbo) возвращает False, так как они не принимают image_b64s.
    """
    ep_low = u_str(endpoint_url or (model_info or {}).get("endpoint", u"")).lower()
    mid_low = u_str((model_info or {}).get("id", u"")).lower()
    slug_low = u_str((model_info or {}).get("slug", u"")).lower()
    mode_low = u_str((model_info or {}).get("mode", u"")).lower()

    for txt_only in (u"imageclassic", u"z-image-turbo", u"qwen-image-2512"):
        if txt_only in ep_low or txt_only in mid_low or txt_only in slug_low:
            return False

    if mode_low == u"img2img_qwen":
        return True
    if u"edit" in ep_low or u"img2img" in ep_low or u"edit" in mid_low or u"img2img" in mid_low:
        return True
    return False


def normalize_b64_images_list(b64_images_or_single):
    """Приводит входные Base64-данные к списку из максимум 3 непустых строк."""
    if not b64_images_or_single:
        return []
    if isinstance(b64_images_or_single, (list, tuple)):
        cleaned = [u_str(x).strip() for x in b64_images_or_single if x and u_str(x).strip()]
        return cleaned[:3]
    single = u_str(b64_images_or_single).strip()
    return [single] if single else []


def compose_effective_prompt(prompt_text, system_prompt_text=u"", use_system_prompt=False):
    """Объединяет системный промпт и пользовательский промпт, если системный промпт включён."""
    p_clean = u_str(prompt_text).strip()
    s_clean = u_str(system_prompt_text).strip()
    if use_system_prompt and s_clean:
        if p_clean:
            return u"{}\n\n{}".format(s_clean, p_clean)
        return s_clean
    return p_clean


def build_generation_payload(
    model_info,
    prompt_text,
    b64_images,
    width,
    height,
    steps_val,
    guidance_val=1.0,
    seed_val=42,
    neg_prompt_text=u"",
    system_prompt_text=u"",
    use_system_prompt=False,
    send_source_image=True,
):
    """
    Формирует строго валидный JSON-payload под конкретную модель Chutes.ai:
      - Qwen-Image-Edit-2511 : prompt, image_b64s, width, height, num_inference_steps, true_cfg_scale, seed (+ negative_prompt)
      - Qwen-Image-2512      : prompt, width, height, num_inference_steps, true_cfg_scale, seed (+ negative_prompt)
      - z-image-turbo        : prompt, width, height, num_inference_steps, seed
      - imageclassic         : prompt, width, height, num_inference_steps, guidance_scale, seed (+ negative_prompt)
    Размеры всегда кратны 64 и не меньше 512px (чтобы исключить HTTP 400: Invalid input parameters).
    """
    mode = u_str(model_info.get("mode", "img2img_qwen"))
    model_id = u_str(model_info.get("id", "Qwen-Image-Edit-2511"))
    endpoint = u_str(model_info.get("endpoint", "")).lower()

    can_accept_images = is_model_img2img(model_info, endpoint)
    b64_list = normalize_b64_images_list(b64_images) if (send_source_image and can_accept_images) else []
    full_prompt = compose_effective_prompt(prompt_text, system_prompt_text, use_system_prompt)
    neg_clean = u_str(neg_prompt_text).strip()
    cfg_float = round(float(guidance_val), 2)
    seed_int = int(seed_val)

    w_valid = max(512, min(2048, int(round(float(width) / 64.0) * 64)))
    h_valid = max(512, min(2048, int(round(float(height) / 64.0) * 64)))
    steps_valid = max(1, min(50, int(steps_val)))

    payload = {
        "prompt": full_prompt,
        "width": w_valid,
        "height": h_valid,
        "num_inference_steps": steps_valid,
        "seed": seed_int,
    }

    if neg_clean and (u"z-image-turbo" not in endpoint):
        payload["negative_prompt"] = neg_clean

    # 1. Модели редактирования по входным кадрам (Qwen-Image-Edit-2511)
    if can_accept_images:
        if len(b64_list) > 0:
            payload["image_b64s"] = b64_list[:3]
        payload["true_cfg_scale"] = max(0.0, min(20.0, cfg_float))
        if mode == u"txt2img_unified" or u"image.chutes.ai" in endpoint:
            payload["model"] = model_id
        return payload

    # 2. Текстовая модель Qwen-Image-2512
    if u"qwen-image-2512" in endpoint or u"qwen-image-2512" in model_id.lower():
        payload["true_cfg_scale"] = max(1.0, min(20.0, cfg_float))
        return payload

    # 3. Быстрая модель z-image-turbo (CFG отключён на уровне модели)
    if u"z-image-turbo" in endpoint or u"z-image-turbo" in model_id.lower():
        payload["num_inference_steps"] = max(1, min(25, steps_valid))
        return payload

    # 4. Классические текстовые модели (imageclassic и стандартные диффузионные модели)
    if u"imageclassic" in endpoint or u"imageclassic" in model_id.lower():
        # imageclassic объединяет 4 пайплайна: juggernaut (SDXL фотореализм), flux (FLUX.1-schnell), dreamshaper, ilustmix
        if endpoint.endswith(u"/image/flux"):
            payload["num_inference_steps"] = max(1, min(8, steps_valid))
            payload["guidance_scale"] = max(0.0, min(10.0, cfg_float))
            payload.pop("negative_prompt", None)
        elif endpoint.endswith(u"/generate"):
            payload["model"] = u"juggernaut"
            payload["guidance_scale"] = max(1.0, min(20.0, cfg_float))
        else:
            payload["guidance_scale"] = max(1.0, min(20.0, cfg_float))
        return payload

    payload["guidance_scale"] = max(1.0, min(20.0, cfg_float))
    if mode == u"txt2img_unified" or u"image.chutes.ai" in endpoint or u"/v1/images" in endpoint:
        payload["model"] = model_id
    return payload


def _extract_chute_base_host(endpoint_url):
    ep = u_str(endpoint_url).strip()
    if u"://" not in ep:
        return u""
    parts = ep.split(u"/")
    if len(parts) >= 3:
        return parts[0] + u"//" + parts[2]
    return ep


def build_fallback_requests_on_error(endpoint_url, payload_dict, model_info=None):
    """
    Формирует список резервных запросов ТОЛЬКО на случай, если основной запрос вернул
    HTTP 400 (Invalid input parameters) или HTTP 404 (если в профиле остался старый путь для imageclassic).
    НИКОГДА не меняет рабочий URL /generate у Qwen-Image-Edit-2511, z-image-turbo и Qwen-Image-2512!
    """
    eff_url = u_str(endpoint_url).strip()
    base_host = _extract_chute_base_host(eff_url)
    fallbacks = []

    p_only = u_str(payload_dict.get("prompt", u""))
    w_v = int(payload_dict.get("width", 1024))
    h_v = int(payload_dict.get("height", 1024))
    st_v = int(payload_dict.get("num_inference_steps", 4))
    cfg_v = float(payload_dict.get("true_cfg_scale", payload_dict.get("guidance_scale", 3.5)))
    sd_v = int(payload_dict.get("seed", 42))

    # 1. Для мульти-пайплайна imageclassic (4 встроенных пайплайна: juggernaut, flux, dreamshaper, ilustmix)
    if u"imageclassic" in eff_url.lower() and base_host:
        fallbacks.append((
            base_host + u"/image/juggernaut",
            {
                "prompt": p_only,
                "width": w_v,
                "height": h_v,
                "num_inference_steps": max(10, min(35, st_v if st_v >= 10 else 20)),
                "guidance_scale": max(1.0, min(15.0, cfg_v)),
                "seed": sd_v,
            },
        ))
        fallbacks.append((
            base_host + u"/image/juggernaut",
            {"prompt": p_only},
        ))
        fallbacks.append((
            base_host + u"/image/flux",
            {
                "prompt": p_only,
                "width": w_v,
                "height": h_v,
                "num_inference_steps": max(1, min(4, st_v)),
                "guidance_scale": 0.0,
                "seed": sd_v,
            },
        ))
        fallbacks.append((
            base_host + u"/image/flux",
            {"prompt": p_only},
        ))
        fallbacks.append((
            base_host + u"/generate",
            {"prompt": p_only, "model": u"juggernaut"},
        ))
        fallbacks.append((
            base_host + u"/generate",
            {"prompt": p_only, "model": u"flux"},
        ))
        return fallbacks

    # 2. Если для обычной модели в поле Эндпоинт случайно оказался внутренний путь вместо /generate
    if base_host and u"chutes.ai" in base_host.lower() and not eff_url.endswith(u"/generate"):
        fallbacks.append((base_host + u"/generate", dict(payload_dict)))

    # 3. Резервы при HTTP 400 (Invalid input parameters) для текстовых моделей (z-image-turbo / Qwen-Image-2512)
    if not payload_dict.get("image_b64s"):
        gen_url = (base_host + u"/generate") if (base_host and u"chutes.ai" in base_host.lower()) else eff_url
        fallbacks.append((
            gen_url,
            {
                "prompt": p_only,
                "width": w_v,
                "height": h_v,
                "num_inference_steps": max(1, min(25, st_v)),
            },
        ))
        fallbacks.append((gen_url, {"prompt": p_only}))

    return fallbacks


def sanitize_filename_part(text, fallback=u"item"):
    """Очищает часть имени файла от недопустимых символов Windows и пробелов."""
    raw = u_str(text).strip()
    if not raw:
        return u_str(fallback)
    forbidden = u'<>:"/\\|?*{}[]\r\n\t'
    out_chars = []
    for ch in raw:
        if ch in forbidden or ch == u" ":
            out_chars.append(u"_")
        else:
            out_chars.append(ch)
    cleaned = u"".join(out_chars)
    while u"__" in cleaned:
        cleaned = cleaned.replace(u"__", u"_")
    cleaned = cleaned.strip(u"_.")
    return cleaned if cleaned else u_str(fallback)


def make_date_and_day_second_stamp():
    """
    Возвращает штамп времени вида YYYYMMDD_SSSSS (например, 20261022_85400),
    где SSSSS — секунда текущих суток (0..86399, в сутках 86400 секунд).
    """
    now_ts = time.time()
    lt = time.localtime(now_ts)
    date_part = u_str(time.strftime("%Y%m%d", lt))
    sec_of_day = int(lt.tm_hour) * 3600 + int(lt.tm_min) * 60 + int(lt.tm_sec)
    return u"{}_{:05d}".format(date_part, sec_of_day)


def build_render_output_base_name(model_name, scene_name, seed_val):
    """
    Формирует имя файла по схеме:
    <выбранная model name из вкладки II>_<имя картинки в Scene #1>_seed<номер сида>_<YYYYMMDD>_<секунда суток>
    """
    m_part = sanitize_filename_part(model_name, u"AI-Model")
    s_part = sanitize_filename_part(scene_name, u"Scene1")
    seed_part = u"seed{}".format(int(seed_val))
    time_part = make_date_and_day_second_stamp()
    return u"{}_{}_{}_{}".format(m_part, s_part, seed_part, time_part)


def parse_and_save_response_bytes(raw_bytes, content_type, out_dir, base_file_name=None):
    """Сохраняет полученные байты изображения (или разбирает JSON с base64) в файл."""
    ct_low = u_str(content_type).lower()

    is_png = (u"png" in ct_low)
    try:
        if len(raw_bytes) >= 4 and int(raw_bytes[0]) == 0x89 and int(raw_bytes[1]) == 0x50:
            is_png = True
        elif len(raw_bytes) >= 2 and int(raw_bytes[0]) == 0xFF and int(raw_bytes[1]) == 0xD8:
            is_png = False
    except Exception:
        pass

    ext = u".png" if is_png else u".jpg"
    base_clean = u_str(base_file_name).strip() if base_file_name else u"chutes_ai_{}".format(make_date_and_day_second_stamp())
    result_path = Path.Combine(out_dir, u"{}{}".format(base_clean, ext))
    if File.Exists(result_path):
        ms_suffix = int((time.time() * 1000) % 1000)
        result_path = Path.Combine(out_dir, u"{}_{:03d}{}".format(base_clean, ms_suffix, ext))

    is_json = (u"json" in ct_low)
    if not is_json:
        try:
            if len(raw_bytes) > 0 and chr(int(raw_bytes[0])) in ("{", "["):
                is_json = True
        except Exception:
            pass

    if is_json:
        json_text = Encoding.UTF8.GetString(raw_bytes)
        data_obj = json.loads(u_str(json_text))
        b64_res = (
            data_obj.get("image")
            or data_obj.get("image_b64")
            or (
                data_obj.get("data", [{}])[0].get("b64_json")
                if isinstance(data_obj.get("data"), list) and len(data_obj.get("data")) > 0
                else None
            )
        )
        if b64_res:
            img_bytes = Convert.FromBase64String(u_str(b64_res))
            write_bytes_to_file(result_path, img_bytes)
            return True, result_path
        return False, u"JSON without image: " + u_str(json_text)

    write_bytes_to_file(result_path, raw_bytes)
    return True, result_path


def curl_post_generation_fallback(endpoint_url, api_key, json_body_str, out_dir, timeout_sec=240, base_file_name=None):
    """
    Резервная отправка POST-запроса через системный curl.exe Windows 10/11,
    если .NET HttpWebRequest в процессе Revit заблокирован прокси или Schannel TLS.
    """
    stamp = u_str(int(time.time() * 1000))
    temp_req_file = Path.Combine(Path.GetTempPath(), u"chutes_req_{}.json".format(stamp))
    temp_resp_file = Path.Combine(Path.GetTempPath(), u"chutes_resp_{}.bin".format(stamp))
    clean_key = u_str(api_key).replace(u"Bearer ", u"").strip()

    try:
        File.WriteAllText(temp_req_file, u_str(json_body_str), Encoding.UTF8)
        for extra_arg in (u"", u'--noproxy "*" '):
            try:
                if File.Exists(temp_resp_file):
                    File.Delete(temp_resp_file)
                args = (
                    u'-sS -k {}--max-time {} -X POST '
                    u'-H "Content-Type: application/json; charset=utf-8" '
                    u'-H "Accept: image/jpeg, image/png, application/json" '
                    u'-H "Authorization: Bearer {}" '
                    u'--data-binary @"{}" '
                    u'-o "{}" -w "%{{http_code}}|%{{content_type}}" "{}"'
                ).format(
                    extra_arg,
                    int(timeout_sec),
                    clean_key,
                    temp_req_file,
                    temp_resp_file,
                    u_str(endpoint_url),
                )
                psi = ProcessStartInfo("curl.exe", args)
                psi.UseShellExecute = False
                psi.CreateNoWindow = True
                psi.RedirectStandardOutput = True
                psi.RedirectStandardError = True
                proc = Process.Start(psi)
                stdout_str = u_str(proc.StandardOutput.ReadToEnd()).strip()
                stderr_str = u_str(proc.StandardError.ReadToEnd()).strip()
                proc.WaitForExit(int(timeout_sec * 1000 + 5000))

                parts = stdout_str.split(u"|", 1)
                code_str = parts[0].strip() if len(parts) > 0 else u""
                ct_str = parts[1].strip() if len(parts) > 1 else u""
                http_code = int(code_str) if code_str.isdigit() else -1

                if http_code == 200 and File.Exists(temp_resp_file):
                    raw_bytes = File.ReadAllBytes(temp_resp_file)
                    if raw_bytes is not None and len(raw_bytes) > 0:
                        ok, res_val = parse_and_save_response_bytes(raw_bytes, ct_str, out_dir, base_file_name=base_file_name)
                        return 200, res_val
                elif http_code > 0 and File.Exists(temp_resp_file):
                    err_text = File.ReadAllText(temp_resp_file, Encoding.UTF8)
                    return http_code, u_str(err_text or stderr_str)
            except Exception:
                pass
    finally:
        for f_tmp in (temp_req_file, temp_resp_file):
            try:
                if File.Exists(f_tmp):
                    File.Delete(f_tmp)
            except Exception:
                pass
    return -1, u""


def _send_single_http_post(endpoint_url, api_key, payload_dict, out_dir, timeout_ms=240000, base_file_name=None):
    """
    Отправляет одиночный POST-запрос на указанный endpoint_url с обходом прокси и резервом через curl.exe.
    """
    configure_network_tls()

    def _do_post_with_mode(target_payload, proxy_mode):
        req = HttpWebRequest.Create(endpoint_url)
        req.Method = "POST"
        req.Timeout = timeout_ms
        req.ReadWriteTimeout = timeout_ms
        req.KeepAlive = False
        req.ContentType = "application/json; charset=utf-8"
        req.Accept = "image/jpeg, image/png, application/json"
        req.UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DynamoRevitAI/3.2"
        try:
            req.ServicePoint.Expect100Continue = False
        except Exception:
            pass
        apply_proxy_mode(req, proxy_mode)

        clean_key = u_str(api_key).replace(u"Bearer ", u"").strip()
        req.Headers.Add("Authorization", "Bearer " + clean_key)

        json_body = json.dumps(target_payload, ensure_ascii=True)
        body_bytes = Encoding.UTF8.GetBytes(json_body)
        req.ContentLength = body_bytes.Length

        req_stream = req.GetRequestStream()
        req_stream.Write(body_bytes, 0, body_bytes.Length)
        req_stream.Close()

        resp = req.GetResponse()
        status_code = Convert.ToInt32(resp.StatusCode)
        content_type = u_str(resp.ContentType).lower()

        resp_stream = resp.GetResponseStream()
        raw_bytes = read_stream_to_bytes(resp_stream)
        resp_stream.Close()
        resp.Close()

        ok, res_val = parse_and_save_response_bytes(raw_bytes, content_type, out_dir, base_file_name=base_file_name)
        return status_code, res_val

    last_code = -1
    last_msg = u""
    proxy_candidates = get_proxy_candidates_for_url(endpoint_url)

    for proxy_mode in proxy_candidates:
        try:
            return _do_post_with_mode(payload_dict, proxy_mode)
        except WebException as web_ex:
            err_code = -1
            err_msg = u_str(web_ex.Message)
            if web_ex.InnerException is not None:
                err_msg = err_msg + u" (" + u_str(web_ex.InnerException.Message) + u")"
            if web_ex.Response is not None:
                try:
                    err_code = Convert.ToInt32(web_ex.Response.StatusCode)
                    reader = StreamReader(web_ex.Response.GetResponseStream(), Encoding.UTF8)
                    body_err = reader.ReadToEnd()
                    reader.Close()
                    if body_err:
                        err_msg = u_str(body_err)
                except Exception:
                    pass
                return err_code, err_msg
            last_code = err_code
            last_msg = err_msg
            reset_service_point(endpoint_url)
        except Exception as ex:
            last_code = -1
            last_msg = u_str(ex)

    json_body_str = json.dumps(payload_dict, ensure_ascii=True)
    c_code, c_res = curl_post_generation_fallback(
        endpoint_url, api_key, json_body_str, out_dir, timeout_sec=max(30, int(timeout_ms / 1000)), base_file_name=base_file_name
    )
    if c_code > 0:
        return c_code, c_res

    return (
        last_code,
        last_msg + u" | Проверьте доступность " + u_str(endpoint_url) + u" в браузере и настройки VPN/прокси.",
    )


def send_image_generation_request(endpoint_url, api_key, payload_dict, out_dir, timeout_ms=240000, model_info=None, base_file_name=None):
    """
    Отправляет POST-запрос напрямую на указанный endpoint_url (без подмены пути через openapi.json,
    чтобы не возникала ошибка HTTP 404: No matching cord found!).
    Если сервер вернул HTTP 400 (Invalid input parameters) или HTTP 404 (на мульти-пайплайне imageclassic),
    автоматически пробует резервные варианты пайплайна/параметров.
    """
    eff_url = u_str(endpoint_url).strip()
    # Если для Qwen-Image-Edit-2511, Qwen-Image-2512 или z-image-turbo в поле Эндпоинт был сбит путь — восстанавливаем /generate
    low_ep = eff_url.lower()
    if any(k in low_ep for k in (u"qwen-image-edit-2511", u"qwen-image-2512", u"z-image-turbo")):
        base_h = _extract_chute_base_host(eff_url)
        if base_h:
            eff_url = base_h.rstrip(u"/") + u"/generate"

    code, res = _send_single_http_post(eff_url, api_key, payload_dict, out_dir, timeout_ms=timeout_ms, base_file_name=base_file_name)
    if code in (400, 404, 422):
        fallbacks = build_fallback_requests_on_error(eff_url, payload_dict, model_info=model_info)
        for fb_url, fb_payload in fallbacks:
            if fb_url == eff_url and fb_payload == payload_dict:
                continue
            fb_code, fb_res = _send_single_http_post(fb_url, api_key, fb_payload, out_dir, timeout_ms=timeout_ms, base_file_name=base_file_name)
            if fb_code == 200:
                return fb_code, fb_res
            if fb_code not in (400, 404, 422) and fb_code > 0:
                code, res = fb_code, fb_res
                break
    return code, res


# ==============================================================================
# 7. ДИАЛОГОВЫЕ ОКНА: СИСТЕМНЫЙ ПРОМПТ, ШАБЛОНЫ ПРОМПТОВ, ПРОСМОТР И СРАВНЕНИЕ
# ==============================================================================


def apply_button_hover(btn, bg_color, border_color=None):
    """Настраивает аккуратную подсветку плоской кнопки WinForms при наведении и нажатии (Revit 2020 / 2022+)."""
    if btn is None or bg_color is None:
        return
    try:
        btn.BackColor = bg_color
        r, g, b = int(bg_color.R), int(bg_color.G), int(bg_color.B)
        lum = (r * 299 + g * 587 + b * 114) // 1000
        if lum > 215:
            if b > r + 8:
                hov = Color.FromArgb(max(0, r - 18), max(0, g - 12), max(0, b - 2))
                prs = Color.FromArgb(max(0, r - 34), max(0, g - 24), max(0, b - 6))
            else:
                hov = Color.FromArgb(max(0, r - 13), max(0, g - 11), max(0, b - 7))
                prs = Color.FromArgb(max(0, r - 25), max(0, g - 21), max(0, b - 15))
        elif lum > 85:
            hov = Color.FromArgb(min(255, r + 18), min(255, g + 18), min(255, b + 20))
            prs = Color.FromArgb(max(0, r - 15), max(0, g - 15), max(0, b - 15))
        else:
            hov = Color.FromArgb(min(255, r + 22), min(255, g + 25), min(255, b + 32))
            prs = Color.FromArgb(max(0, r + 8), max(0, g + 10), max(0, b + 14))
        btn.FlatAppearance.MouseOverBackColor = hov
        btn.FlatAppearance.MouseDownBackColor = prs
        if border_color is not None:
            btn.FlatAppearance.BorderColor = border_color
    except Exception:
        pass


def style_subdialog_controls(dlg, is_dark=False):
    """Применяет аккуратный hover к кнопкам модальных под-окон и синхронизирует светлую/тёмную тему."""
    if dlg is None:
        return
    try:
        if is_dark:
            dlg.BackColor = Color.FromArgb(22, 27, 36)
        for ctrl in dlg.Controls:
            if isinstance(ctrl, Button):
                role = u_str(getattr(ctrl, "Tag", u""))
                if role == u"primary_dark":
                    bg = GRAPHITE_BTN_DARK if is_dark else GRAPHITE_BTN_LIGHT
                    ctrl.ForeColor = Color.White
                    brd = Color.FromArgb(82, 98, 122) if is_dark else Color.FromArgb(51, 65, 85)
                    apply_button_hover(ctrl, bg, brd)
                    continue
                bg = ctrl.BackColor
                if is_dark:
                    if int(bg.R) == 255 and int(bg.G) == 255 and int(bg.B) == 255:
                        bg = Color.FromArgb(32, 39, 52)
                        if int(ctrl.ForeColor.R) < 120 and int(ctrl.ForeColor.B) < 150:
                            ctrl.ForeColor = Color.FromArgb(226, 232, 240)
                    elif int(bg.R) == 239 and int(bg.G) == 246 and int(bg.B) == 255:
                        bg = Color.FromArgb(30, 58, 95)
                        ctrl.ForeColor = Color.FromArgb(96, 165, 250)
                brd = Color.FromArgb(56, 68, 89) if (is_dark and int(bg.R) < 40 and int(bg.B) < 100) else bg
                apply_button_hover(ctrl, bg, brd)
            elif is_dark and isinstance(ctrl, (TextBox, ListBox)):
                ctrl.BackColor = Color.FromArgb(24, 30, 42)
                ctrl.ForeColor = Color.FromArgb(226, 232, 240)
            elif is_dark and isinstance(ctrl, (Label, CheckBox)):
                ctrl.ForeColor = Color.FromArgb(226, 232, 240) if ctrl.Font.Bold else Color.FromArgb(148, 163, 184)
    except Exception:
        pass


def show_system_prompt_dialog(parent_form, profiles_data):
    """Модальное окно настройки Системного промпта (System Prompt)."""
    dlg = Form()
    dlg.Text = u"System Prompt Settings"
    dlg.Size = Size(640, 360)
    dlg.MinimumSize = Size(520, 300)
    dlg.FormBorderStyle = FormBorderStyle.FixedDialog
    dlg.StartPosition = FormStartPosition.CenterParent
    dlg.MaximizeBox = False
    dlg.MinimizeBox = False
    dlg.BackColor = Color.FromArgb(246, 248, 250)

    font_sec = Font("Segoe UI", 9.5, FontStyle.Bold)
    font_reg = Font("Segoe UI", 9.0, FontStyle.Regular)
    font_small = Font("Segoe UI", 8.25, FontStyle.Regular)

    chk_enable = CheckBox()
    chk_enable.Text = u"Enable System Prompt (automatically prepend to generation requests)"
    chk_enable.Font = font_sec
    chk_enable.ForeColor = Color.FromArgb(15, 23, 42)
    chk_enable.Location = Point(18, 16)
    chk_enable.Size = Size(585, 24)
    chk_enable.Checked = bool(profiles_data.get("use_system_prompt", False))
    dlg.Controls.Add(chk_enable)

    lbl_hint = Label()
    lbl_hint.Text = u"Defines global instructions for the AI model (preserving 3D CAD geometry, perspective, and style):"
    lbl_hint.Font = font_small
    lbl_hint.ForeColor = Color.FromArgb(100, 116, 139)
    lbl_hint.Location = Point(18, 44)
    lbl_hint.Size = Size(585, 18)
    dlg.Controls.Add(lbl_hint)

    txt_sys = TextBox()
    txt_sys.Location = Point(18, 66)
    txt_sys.Size = Size(588, 190)
    txt_sys.Multiline = True
    txt_sys.ScrollBars = ScrollBars.Vertical
    txt_sys.Font = font_reg
    txt_sys.Text = u_str(profiles_data.get("system_prompt", DEFAULT_SYSTEM_PROMPT))
    enable_textbox_clipboard(txt_sys)
    dlg.Controls.Add(txt_sys)

    btn_paste_sys = Button()
    btn_paste_sys.Text = u"Paste Clipboard"
    btn_paste_sys.FlatStyle = FlatStyle.Flat
    btn_paste_sys.BackColor = Color.FromArgb(239, 246, 255)
    btn_paste_sys.ForeColor = Color.FromArgb(37, 99, 235)
    btn_paste_sys.Font = font_small
    btn_paste_sys.Location = Point(156, 268)
    btn_paste_sys.Size = Size(140, 32)
    btn_paste_sys.Cursor = Cursors.Hand
    btn_paste_sys.Click += lambda s, a: paste_into_textbox(txt_sys)
    dlg.Controls.Add(btn_paste_sys)

    btn_reset = Button()
    btn_reset.Text = u"Reset Default"
    btn_reset.FlatStyle = FlatStyle.Flat
    btn_reset.BackColor = Color.White
    btn_reset.ForeColor = Color.FromArgb(100, 116, 139)
    btn_reset.Font = font_small
    btn_reset.Location = Point(18, 268)
    btn_reset.Size = Size(130, 32)
    btn_reset.Cursor = Cursors.Hand
    btn_reset.Click += lambda s, a: setattr(txt_sys, "Text", DEFAULT_SYSTEM_PROMPT)
    dlg.Controls.Add(btn_reset)

    btn_cancel = Button()
    btn_cancel.Text = u"Cancel"
    btn_cancel.FlatStyle = FlatStyle.Flat
    btn_cancel.BackColor = Color.White
    btn_cancel.ForeColor = Color.FromArgb(30, 41, 59)
    btn_cancel.Font = font_reg
    btn_cancel.Location = Point(368, 268)
    btn_cancel.Size = Size(110, 32)
    btn_cancel.Cursor = Cursors.Hand
    btn_cancel.Click += lambda s, a: dlg.Close()
    dlg.Controls.Add(btn_cancel)

    saved_flag = {"ok": False}

    def _on_save(s, a):
        profiles_data["use_system_prompt"] = bool(chk_enable.Checked)
        profiles_data["system_prompt"] = u_str(txt_sys.Text).strip()
        save_profiles_data(profiles_data)
        saved_flag["ok"] = True
        dlg.Close()

    btn_save = Button()
    btn_save.Text = u"Save"
    btn_save.FlatStyle = FlatStyle.Flat
    btn_save.BackColor = Color.FromArgb(37, 99, 235)
    btn_save.ForeColor = Color.White
    btn_save.Font = font_sec
    btn_save.Location = Point(486, 268)
    btn_save.Size = Size(120, 32)
    btn_save.Cursor = Cursors.Hand
    btn_save.Click += _on_save
    dlg.Controls.Add(btn_save)

    style_subdialog_controls(dlg, is_dark=bool(profiles_data.get("ui_dark_mode", False)))
    dlg.ShowDialog(parent_form)
    return saved_flag["ok"]


def show_prompt_templates_dialog(parent_form, profiles_data, target_textbox, is_negative=False):
    """
    Окно управления шаблонами промптов (отдельно для обычного промпта и для негативного промпта).
    Позволяет выбирать, редактировать, сохранять новые и применять шаблоны.
    """
    storage_key = "neg_prompt_templates" if is_negative else "prompt_templates"
    default_list = DEFAULT_NEG_TEMPLATES if is_negative else DEFAULT_POS_TEMPLATES
    if storage_key not in profiles_data or not isinstance(profiles_data[storage_key], list):
        profiles_data[storage_key] = list(default_list)
    templates_list = profiles_data[storage_key]

    dlg = Form()
    dlg.Text = u"Negative Prompt Templates" if is_negative else u"Prompt Templates"
    dlg.Size = Size(760, 480)
    dlg.MinimumSize = Size(700, 430)
    dlg.FormBorderStyle = FormBorderStyle.Sizable
    dlg.StartPosition = FormStartPosition.CenterParent
    dlg.MaximizeBox = True
    dlg.MinimizeBox = True
    dlg.BackColor = Color.FromArgb(246, 248, 250)

    font_sec = Font("Segoe UI", 9.5, FontStyle.Bold)
    font_reg = Font("Segoe UI", 9.0, FontStyle.Regular)
    font_small = Font("Segoe UI", 8.25, FontStyle.Regular)

    lbl_list = Label()
    lbl_list.Text = u"Saved Templates"
    lbl_list.Font = font_sec
    lbl_list.ForeColor = Color.FromArgb(15, 23, 42)
    lbl_list.Location = Point(16, 14)
    lbl_list.Size = Size(260, 20)
    dlg.Controls.Add(lbl_list)

    lst_tpl = ListBox()
    lst_tpl.Location = Point(16, 38)
    lst_tpl.Size = Size(270, 336)
    lst_tpl.Font = font_reg
    dlg.Controls.Add(lst_tpl)

    lbl_name = Label()
    lbl_name.Text = u"Template Name"
    lbl_name.Font = font_sec
    lbl_name.ForeColor = Color.FromArgb(15, 23, 42)
    lbl_name.Location = Point(302, 14)
    lbl_name.Size = Size(200, 20)
    dlg.Controls.Add(lbl_name)

    txt_name = TextBox()
    txt_name.Location = Point(302, 38)
    txt_name.Size = Size(424, 24)
    txt_name.Font = font_reg
    enable_textbox_clipboard(txt_name)
    dlg.Controls.Add(txt_name)

    lbl_body = Label()
    lbl_body.Text = u"Template Text"
    lbl_body.Font = font_sec
    lbl_body.ForeColor = Color.FromArgb(15, 23, 42)
    lbl_body.Location = Point(302, 70)
    lbl_body.Size = Size(200, 20)
    dlg.Controls.Add(lbl_body)

    btn_from_current = Button()
    btn_from_current.Text = u"Insert Current Prompt Text"
    btn_from_current.FlatStyle = FlatStyle.Flat
    btn_from_current.BackColor = Color.FromArgb(239, 246, 255)
    btn_from_current.ForeColor = Color.FromArgb(37, 99, 235)
    btn_from_current.Font = font_small
    btn_from_current.Location = Point(536, 66)
    btn_from_current.Size = Size(190, 24)
    btn_from_current.Cursor = Cursors.Hand
    dlg.Controls.Add(btn_from_current)

    txt_body = TextBox()
    txt_body.Location = Point(302, 94)
    txt_body.Size = Size(424, 224)
    txt_body.Multiline = True
    txt_body.ScrollBars = ScrollBars.Vertical
    txt_body.Font = font_reg
    enable_textbox_clipboard(txt_body)
    dlg.Controls.Add(txt_body)

    btn_add_new = Button()
    btn_add_new.Text = u"Save as New Template"
    btn_add_new.FlatStyle = FlatStyle.Flat
    btn_add_new.BackColor = Color.FromArgb(239, 246, 255)
    btn_add_new.ForeColor = Color.FromArgb(37, 99, 235)
    btn_add_new.Font = font_small
    btn_add_new.Location = Point(302, 326)
    btn_add_new.Size = Size(156, 28)
    btn_add_new.Cursor = Cursors.Hand
    dlg.Controls.Add(btn_add_new)

    btn_update_sel = Button()
    btn_update_sel.Text = u"Update Template"
    btn_update_sel.FlatStyle = FlatStyle.Flat
    btn_update_sel.BackColor = Color.White
    btn_update_sel.ForeColor = Color.FromArgb(30, 41, 59)
    btn_update_sel.Font = font_small
    btn_update_sel.Location = Point(464, 326)
    btn_update_sel.Size = Size(156, 28)
    btn_update_sel.Cursor = Cursors.Hand
    dlg.Controls.Add(btn_update_sel)

    btn_del_sel = Button()
    btn_del_sel.Text = u"✕ Delete"
    btn_del_sel.FlatStyle = FlatStyle.Flat
    btn_del_sel.BackColor = Color.White
    btn_del_sel.ForeColor = Color.FromArgb(220, 38, 38)
    btn_del_sel.Font = font_small
    btn_del_sel.Location = Point(626, 326)
    btn_del_sel.Size = Size(100, 28)
    btn_del_sel.Cursor = Cursors.Hand
    dlg.Controls.Add(btn_del_sel)

    btn_apply_replace = Button()
    btn_apply_replace.Text = u"Replace Current"
    btn_apply_replace.FlatStyle = FlatStyle.Flat
    btn_apply_replace.BackColor = Color.FromArgb(16, 185, 129)
    btn_apply_replace.ForeColor = Color.White
    btn_apply_replace.Font = font_sec
    btn_apply_replace.Location = Point(302, 388)
    btn_apply_replace.Size = Size(166, 36)
    btn_apply_replace.Cursor = Cursors.Hand
    dlg.Controls.Add(btn_apply_replace)

    btn_apply_append = Button()
    btn_apply_append.Text = u"Add to Current"
    btn_apply_append.FlatStyle = FlatStyle.Flat
    btn_apply_append.BackColor = Color.FromArgb(37, 99, 235)
    btn_apply_append.ForeColor = Color.White
    btn_apply_append.Font = font_sec
    btn_apply_append.Location = Point(476, 388)
    btn_apply_append.Size = Size(166, 36)
    btn_apply_append.Cursor = Cursors.Hand
    dlg.Controls.Add(btn_apply_append)

    btn_close = Button()
    btn_close.Text = u"Close"
    btn_close.Tag = u"primary_dark"
    btn_close.FlatStyle = FlatStyle.Flat
    btn_close.BackColor = Color.FromArgb(71, 85, 105)
    btn_close.ForeColor = Color.White
    btn_close.Font = font_sec
    btn_close.Location = Point(650, 388)
    btn_close.Size = Size(76, 36)
    btn_close.Cursor = Cursors.Hand
    btn_close.Click += lambda s, a: dlg.Close()
    dlg.Controls.Add(btn_close)

    def _refresh_list(select_idx=0):
        lst_tpl.Items.Clear()
        for t in templates_list:
            lst_tpl.Items.Add(u_str(t.get("name", u"Template")))
        if lst_tpl.Items.Count > 0:
            idx = max(0, min(lst_tpl.Items.Count - 1, int(select_idx)))
            lst_tpl.SelectedIndex = idx

    def _on_sel_changed(s, a):
        idx = lst_tpl.SelectedIndex
        if 0 <= idx < len(templates_list):
            t = templates_list[idx]
            txt_name.Text = u_str(t.get("name", u""))
            txt_body.Text = u_str(t.get("text", u""))

    lst_tpl.SelectedIndexChanged += _on_sel_changed

    def _on_grab_current(s, a):
        curr = u_str(target_textbox.Text).strip()
        if curr:
            txt_body.Text = curr
            if not u_str(txt_name.Text).strip():
                txt_name.Text = u"Custom Template {}".format(len(templates_list) + 1)

    btn_from_current.Click += _on_grab_current

    def _on_add_new(s, a):
        name_val = u_str(txt_name.Text).strip() or u"Template {}".format(len(templates_list) + 1)
        body_val = u_str(txt_body.Text).strip()
        if not body_val:
            return
        templates_list.append({"name": name_val, "text": body_val})
        save_profiles_data(profiles_data)
        _refresh_list(len(templates_list) - 1)

    btn_add_new.Click += _on_add_new

    def _on_update_sel(s, a):
        idx = lst_tpl.SelectedIndex
        name_val = u_str(txt_name.Text).strip()
        body_val = u_str(txt_body.Text).strip()
        if 0 <= idx < len(templates_list) and body_val:
            templates_list[idx] = {
                "name": name_val or u_str(templates_list[idx].get("name", u"Template")),
                "text": body_val,
            }
            save_profiles_data(profiles_data)
            _refresh_list(idx)

    btn_update_sel.Click += _on_update_sel

    def _on_del_sel(s, a):
        idx = lst_tpl.SelectedIndex
        if 0 <= idx < len(templates_list):
            del templates_list[idx]
            save_profiles_data(profiles_data)
            _refresh_list(max(0, idx - 1))

    btn_del_sel.Click += _on_del_sel

    def _on_replace(s, a):
        body_val = u_str(txt_body.Text).strip()
        if body_val:
            target_textbox.Text = body_val
        dlg.Close()

    def _on_append(s, a):
        body_val = u_str(txt_body.Text).strip()
        if body_val:
            curr = u_str(target_textbox.Text).strip()
            if curr:
                sep = u", " if not curr.endswith(u",") else u" "
                target_textbox.Text = curr + sep + body_val
            else:
                target_textbox.Text = body_val
        dlg.Close()

    btn_apply_replace.Click += _on_replace
    btn_apply_append.Click += _on_append
    lst_tpl.DoubleClick += _on_replace

    def _layout_tpl(s=None, a=None):
        cw = dlg.ClientSize.Width
        ch = dlg.ClientSize.Height
        if cw < 500 or ch < 320:
            return
        left_w = max(240, int(cw * 0.36))
        right_x = 16 + left_w + 16
        right_w = max(320, cw - right_x - 16)
        bot_y = ch - 52
        mid_btns_y = bot_y - 42

        lst_tpl.Location = Point(16, 38)
        lst_tpl.Size = Size(left_w, max(180, bot_y - 38 + 36))

        lbl_name.Location = Point(right_x, 14)
        txt_name.Location = Point(right_x, 38)
        txt_name.Size = Size(right_w, 24)

        lbl_body.Location = Point(right_x, 70)
        btn_from_current.Location = Point(right_x + right_w - 190, 66)
        txt_body.Location = Point(right_x, 94)
        txt_body.Size = Size(right_w, max(120, mid_btns_y - 94 - 8))

        del_w = 100
        pair_top_w = max(140, (right_w - del_w - 12) // 2)
        btn_add_new.Location = Point(right_x, mid_btns_y)
        btn_add_new.Size = Size(pair_top_w, 28)
        btn_update_sel.Location = Point(right_x + pair_top_w + 6, mid_btns_y)
        btn_update_sel.Size = Size(pair_top_w, 28)
        btn_del_sel.Location = Point(right_x + right_w - del_w, mid_btns_y)
        btn_del_sel.Size = Size(del_w, 28)

        close_w = 84
        pair_bot_w = max(150, (right_w - close_w - 16) // 2)
        btn_apply_replace.Location = Point(right_x, bot_y)
        btn_apply_replace.Size = Size(pair_bot_w, 36)
        btn_apply_append.Location = Point(right_x + pair_bot_w + 8, bot_y)
        btn_apply_append.Size = Size(pair_bot_w, 36)
        btn_close.Location = Point(right_x + right_w - close_w, bot_y)
        btn_close.Size = Size(close_w, 36)

    dlg.Resize += _layout_tpl
    _refresh_list(0)
    is_dark_dlg = bool(profiles_data.get("ui_dark_mode", False))
    style_subdialog_controls(dlg, is_dark=is_dark_dlg)
    try:
        txt_body.Font = Font("Segoe UI", 9.0, FontStyle.Bold if PROMPT_TEXT_BOLD else FontStyle.Regular)
        if is_negative:
            txt_body.ForeColor = NEG_PROMPT_COLOR_DARK if is_dark_dlg else NEG_PROMPT_COLOR_LIGHT
        else:
            txt_body.ForeColor = PROMPT_COLOR_DARK if is_dark_dlg else PROMPT_COLOR_LIGHT
    except Exception:
        pass
    _layout_tpl()
    dlg.ShowDialog(parent_form)


def show_full_image_window(image_path, title_text, live_bitmap=None):
    """Открывает актуальное изображение в отдельном растягиваемом окне при нажатии на превью."""
    img_obj = None
    if live_bitmap is not None:
        try:
            img_obj = Bitmap(live_bitmap)
        except Exception:
            img_obj = None
    if img_obj is None and image_path and File.Exists(image_path):
        img_obj = load_image_unlocked(image_path)
    if img_obj is None:
        return

    viewer = Form()
    dims_str = u"{}x{} px".format(img_obj.Width, img_obj.Height)
    fname_str = Path.GetFileName(image_path) if image_path else u"preview.png"
    viewer.Text = u"{}  —  {}  ({})".format(u_str(title_text), fname_str, dims_str)
    viewer.Size = Size(1150, 800)
    viewer.MinimumSize = Size(640, 480)
    viewer.FormBorderStyle = FormBorderStyle.Sizable
    viewer.StartPosition = FormStartPosition.CenterScreen
    viewer.MaximizeBox = True
    viewer.MinimizeBox = True
    viewer.BackColor = Color.FromArgb(15, 23, 42)

    pic = PictureBox()
    pic.SizeMode = PictureBoxSizeMode.Zoom
    pic.BackColor = Color.FromArgb(15, 23, 42)
    pic.Image = img_obj
    viewer.Controls.Add(pic)

    pnl_bottom = Panel()
    pnl_bottom.BackColor = Color.FromArgb(30, 41, 59)
    viewer.Controls.Add(pnl_bottom)

    lbl_info = Label()
    lbl_info.Text = u"Resolution: {}   |   File: {}".format(dims_str, u_str(image_path or fname_str))
    lbl_info.ForeColor = Color.FromArgb(226, 232, 240)
    lbl_info.Font = Font("Segoe UI", 9.0, FontStyle.Regular)
    lbl_info.Location = Point(16, 10)
    lbl_info.Size = Size(820, 32)
    pnl_bottom.Controls.Add(lbl_info)

    btn_close = Button()
    btn_close.Text = u"CLOSE"
    btn_close.FlatStyle = FlatStyle.Flat
    btn_close.BackColor = Color.FromArgb(220, 38, 38)
    btn_close.ForeColor = Color.White
    btn_close.Font = Font("Segoe UI", 9.0, FontStyle.Bold)
    btn_close.Size = Size(150, 34)
    btn_close.Cursor = Cursors.Hand
    apply_button_hover(btn_close, btn_close.BackColor, btn_close.BackColor)
    btn_close.Click += lambda s, a: viewer.Close()
    pnl_bottom.Controls.Add(btn_close)

    def _layout_viewer(s=None, a=None):
        cw = viewer.ClientSize.Width
        ch = viewer.ClientSize.Height
        bar_h = 52
        pic.Location = Point(0, 0)
        pic.Size = Size(cw, max(100, ch - bar_h))
        pnl_bottom.Location = Point(0, max(100, ch - bar_h))
        pnl_bottom.Size = Size(cw, bar_h)
        lbl_info.Size = Size(max(200, cw - 190), 34)
        btn_close.Location = Point(max(200, cw - 166), 9)

    def _on_viewer_closed(s, a):
        try:
            if pic.Image is not None:
                pic.Image.Dispose()
        except Exception:
            pass

    viewer.Resize += _layout_viewer
    viewer.FormClosed += _on_viewer_closed
    _layout_viewer()
    viewer.Show()


def create_scaled_bitmap(src_img, target_w, target_h):
    """Масштабирует изображение под заданный размер (target_w x target_h) для быстрого рендера шторки."""
    if src_img is None or target_w <= 1 or target_h <= 1:
        return None
    bmp = Bitmap(int(target_w), int(target_h))
    g = Graphics.FromImage(bmp)
    try:
        try:
            g.InterpolationMode = InterpolationMode.HighQualityBicubic
            g.SmoothingMode = SmoothingMode.AntiAlias
        except Exception:
            pass
        g.DrawImage(src_img, Rectangle(0, 0, int(target_w), int(target_h)))
    finally:
        g.Dispose()
    return bmp


def show_comparison_window(input_items, res_path, view_label, prompt_text, model_title=u"Chutes.ai"):
    """
    Интерактивное окно сравнения «До / После» с наложением двух изображений друг на друга
    и подвижным ползунком-шторкой (влево/вправо), а также выбором кадра для сравнения.
    """
    valid_inputs = []
    if isinstance(input_items, (list, tuple)):
        for item in input_items:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                t_lbl, f_path = item[0], item[1]
                if f_path and File.Exists(u_str(f_path)):
                    valid_inputs.append([u_str(t_lbl), u_str(f_path)])
    elif isinstance(input_items, STRING_TYPES) and File.Exists(u_str(input_items)):
        valid_inputs.append([u"Scene #1 (Source)", u_str(input_items)])

    has_result = bool(res_path and File.Exists(u_str(res_path)))
    if len(valid_inputs) == 0 and not has_result:
        return

    if len(valid_inputs) == 0 and has_result:
        valid_inputs.append([u"AI Render", u_str(res_path)])

    after_path = u_str(res_path) if has_result else valid_inputs[-1][1]
    after_label = u_str(model_title) if has_result else valid_inputs[-1][0]

    form = Form()
    form.Text = u"Before / After"
    form.Size = Size(1240, 840)
    form.MinimumSize = Size(960, 620)
    form.FormBorderStyle = FormBorderStyle.Sizable
    form.StartPosition = FormStartPosition.CenterScreen
    form.MaximizeBox = True
    form.MinimizeBox = True
    form.BackColor = Color.FromArgb(15, 23, 42)

    font_bold = Font("Segoe UI", 9.5, FontStyle.Bold)
    font_reg = Font("Segoe UI", 9.0, FontStyle.Regular)
    font_small = Font("Segoe UI", 8.25, FontStyle.Regular)
    font_badge = Font("Segoe UI", 9.0, FontStyle.Bold)

    pnl_top = Panel()
    pnl_top.BackColor = Color.FromArgb(30, 41, 59)
    pnl_top.Location = Point(0, 0)
    pnl_top.Size = Size(1240, 50)
    form.Controls.Add(pnl_top)

    lbl_sel = Label()
    lbl_sel.Text = u"Before (Left):"
    lbl_sel.ForeColor = Color.FromArgb(226, 232, 240)
    lbl_sel.Font = font_bold
    lbl_sel.Location = Point(16, 15)
    lbl_sel.Size = Size(104, 22)
    pnl_top.Controls.Add(lbl_sel)

    cmb_input = ComboBox()
    cmb_input.DropDownStyle = ComboBoxStyle.DropDownList
    cmb_input.Font = font_reg
    cmb_input.Location = Point(124, 12)
    cmb_input.Size = Size(300, 26)
    for item in valid_inputs:
        cmb_input.Items.Add(item[0])
    if cmb_input.Items.Count > 0:
        cmb_input.SelectedIndex = 0
    pnl_top.Controls.Add(cmb_input)

    btn_add_file = Button()
    btn_add_file.Text = u"Select File..."
    btn_add_file.FlatStyle = FlatStyle.Flat
    btn_add_file.FlatAppearance.BorderColor = Color.FromArgb(71, 85, 105)
    btn_add_file.BackColor = Color.FromArgb(51, 65, 85)
    btn_add_file.ForeColor = Color.White
    btn_add_file.Font = font_small
    btn_add_file.Location = Point(432, 11)
    btn_add_file.Size = Size(106, 27)
    btn_add_file.Cursor = Cursors.Hand
    pnl_top.Controls.Add(btn_add_file)

    lbl_vs = Label()
    lbl_vs.Text = after_label
    lbl_vs.ForeColor = Color.FromArgb(16, 185, 129)
    lbl_vs.Font = font_bold
    lbl_vs.Location = Point(632, 15)
    lbl_vs.Size = Size(340, 22)
    pnl_top.Controls.Add(lbl_vs)

    btn_full_before = Button()
    btn_full_before.Text = u"Open Before"
    btn_full_before.FlatStyle = FlatStyle.Flat
    btn_full_before.FlatAppearance.BorderColor = Color.FromArgb(71, 85, 105)
    btn_full_before.BackColor = Color.FromArgb(30, 41, 59)
    btn_full_before.ForeColor = Color.FromArgb(226, 232, 240)
    btn_full_before.Font = font_small
    btn_full_before.Size = Size(98, 27)
    btn_full_before.Cursor = Cursors.Hand
    pnl_top.Controls.Add(btn_full_before)

    btn_full_after = Button()
    btn_full_after.Text = u"Open After"
    btn_full_after.FlatStyle = FlatStyle.Flat
    btn_full_after.FlatAppearance.BorderColor = Color.FromArgb(16, 185, 129)
    btn_full_after.BackColor = Color.FromArgb(5, 150, 105)
    btn_full_after.ForeColor = Color.White
    btn_full_after.Font = font_small
    btn_full_after.Size = Size(112, 27)
    btn_full_after.Cursor = Cursors.Hand
    pnl_top.Controls.Add(btn_full_after)

    pic_canvas = PictureBox()
    pic_canvas.SizeMode = PictureBoxSizeMode.Normal
    pic_canvas.BackColor = Color.FromArgb(15, 23, 42)
    pic_canvas.Cursor = Cursors.SizeWE
    form.Controls.Add(pic_canvas)

    pnl_bottom = Panel()
    pnl_bottom.BackColor = Color.FromArgb(30, 41, 59)
    pnl_bottom.Location = Point(0, 720)
    pnl_bottom.Size = Size(1240, 82)
    form.Controls.Add(pnl_bottom)

    btn_only_after = Button()
    btn_only_after.Text = u"AFTER"
    btn_only_after.FlatStyle = FlatStyle.Flat
    btn_only_after.FlatAppearance.BorderColor = Color.FromArgb(71, 85, 105)
    btn_only_after.BackColor = Color.FromArgb(51, 65, 85)
    btn_only_after.ForeColor = Color.White
    btn_only_after.Font = font_small
    btn_only_after.Location = Point(16, 8)
    btn_only_after.Size = Size(102, 26)
    btn_only_after.Cursor = Cursors.Hand
    pnl_bottom.Controls.Add(btn_only_after)

    btn_center_split = Button()
    btn_center_split.Text = u"50% | 50%"
    btn_center_split.FlatStyle = FlatStyle.Flat
    btn_center_split.FlatAppearance.BorderColor = Color.FromArgb(16, 185, 129)
    btn_center_split.BackColor = Color.FromArgb(16, 185, 129)
    btn_center_split.ForeColor = Color.White
    btn_center_split.Font = font_small
    btn_center_split.Location = Point(124, 8)
    btn_center_split.Size = Size(80, 26)
    btn_center_split.Cursor = Cursors.Hand
    pnl_bottom.Controls.Add(btn_center_split)

    btn_only_before = Button()
    btn_only_before.Text = u"BEFORE"
    btn_only_before.FlatStyle = FlatStyle.Flat
    btn_only_before.FlatAppearance.BorderColor = Color.FromArgb(71, 85, 105)
    btn_only_before.BackColor = Color.FromArgb(51, 65, 85)
    btn_only_before.ForeColor = Color.White
    btn_only_before.Font = font_small
    btn_only_before.Location = Point(210, 8)
    btn_only_before.Size = Size(102, 26)
    btn_only_before.Cursor = Cursors.Hand
    pnl_bottom.Controls.Add(btn_only_before)

    lbl_slider_val = Label()
    lbl_slider_val.Text = u"50%"
    lbl_slider_val.ForeColor = Color.FromArgb(148, 163, 184)
    lbl_slider_val.Font = font_small
    lbl_slider_val.Location = Point(328, 12)
    lbl_slider_val.Size = Size(430, 20)
    pnl_bottom.Controls.Add(lbl_slider_val)

    slider = TrackBar()
    slider.Minimum = 0
    slider.Maximum = 1000
    slider.Value = 500
    slider.TickStyle = getattr(TickStyle, "None", TickStyle.BottomRight)
    slider.AutoSize = False
    slider.BackColor = Color.FromArgb(30, 41, 59)
    slider.Location = Point(760, 7)
    slider.Size = Size(460, 28)
    slider.Cursor = Cursors.Hand
    pnl_bottom.Controls.Add(slider)

    lbl_prompt = Label()
    lbl_prompt.Text = u"Prompt: " + u_str(prompt_text)
    lbl_prompt.ForeColor = Color.FromArgb(203, 213, 225)
    lbl_prompt.Font = font_small
    lbl_prompt.Location = Point(16, 42)
    lbl_prompt.Size = Size(1040, 32)
    pnl_bottom.Controls.Add(lbl_prompt)

    btn_close = Button()
    btn_close.Text = u"CLOSE"
    btn_close.FlatStyle = FlatStyle.Flat
    btn_close.FlatAppearance.BorderColor = Color.FromArgb(82, 98, 122)
    btn_close.BackColor = GRAPHITE_BTN_DARK
    btn_close.ForeColor = Color.White
    btn_close.Font = font_bold
    btn_close.Size = Size(156, 34)
    btn_close.Cursor = Cursors.Hand
    btn_close.Click += lambda s, a: form.Close()
    pnl_bottom.Controls.Add(btn_close)

    state = {
        "before_orig": load_image_unlocked(valid_inputs[0][1]),
        "after_orig": load_image_unlocked(after_path),
        "before_title": valid_inputs[0][0],
        "before_path": valid_inputs[0][1],
        "scaled_before": None,
        "scaled_after": None,
        "comp_bmp": None,
        "draw_x": 0,
        "draw_y": 0,
        "draw_w": 100,
        "draw_h": 100,
        "split_ratio": 0.5,
        "dragging": False,
        "updating_slider": False,
    }

    def _dispose_scaled_cache():
        for k in ("scaled_before", "scaled_after"):
            if state[k] is not None:
                try:
                    state[k].Dispose()
                except Exception:
                    pass
                state[k] = None

    def _rebuild_scaled_cache():
        _dispose_scaled_cache()
        cw = max(100, pic_canvas.Width)
        ch = max(100, pic_canvas.Height)

        ref_img = state["after_orig"] or state["before_orig"]
        if ref_img is None:
            return

        iw = max(1, ref_img.Width)
        ih = max(1, ref_img.Height)
        pad_x = 20
        pad_y = 16
        avail_w = max(80, cw - pad_x * 2)
        avail_h = max(80, ch - pad_y * 2)

        scale = min(float(avail_w) / float(iw), float(avail_h) / float(ih))
        dw = max(40, int(round(iw * scale)))
        dh = max(40, int(round(ih * scale)))
        dx = int((cw - dw) // 2)
        dy = int((ch - dh) // 2)

        state["draw_x"] = dx
        state["draw_y"] = dy
        state["draw_w"] = dw
        state["draw_h"] = dh

        if state["before_orig"] is not None:
            state["scaled_before"] = create_scaled_bitmap(state["before_orig"], dw, dh)
        if state["after_orig"] is not None:
            state["scaled_after"] = create_scaled_bitmap(state["after_orig"], dw, dh)

        if state["comp_bmp"] is None or state["comp_bmp"].Width != cw or state["comp_bmp"].Height != ch:
            old_bmp = state["comp_bmp"]
            state["comp_bmp"] = Bitmap(cw, ch)
            pic_canvas.Image = state["comp_bmp"]
            if old_bmp is not None:
                try:
                    old_bmp.Dispose()
                except Exception:
                    pass

    def _render_split_frame():
        if state["comp_bmp"] is None:
            _rebuild_scaled_cache()
        bmp = state["comp_bmp"]
        if bmp is None:
            return

        dx = state["draw_x"]
        dy = state["draw_y"]
        dw = state["draw_w"]
        dh = state["draw_h"]
        ratio = max(0.0, min(1.0, float(state["split_ratio"])))
        split_px = int(round(dw * ratio))
        line_x = dx + split_px

        g = Graphics.FromImage(bmp)
        try:
            try:
                g.SmoothingMode = SmoothingMode.AntiAlias
                g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit
            except Exception:
                pass

            g.Clear(Color.FromArgb(15, 23, 42))

            if state["scaled_after"] is not None:
                g.DrawImage(state["scaled_after"], dx, dy)
            elif state["scaled_before"] is not None:
                g.DrawImage(state["scaled_before"], dx, dy)

            if state["scaled_before"] is not None and split_px > 0:
                g.SetClip(Rectangle(dx, dy, split_px, dh))
                g.DrawImage(state["scaled_before"], dx, dy)
                g.ResetClip()

            pen_border = Pen(Color.FromArgb(71, 85, 105), 1.0)
            g.DrawRectangle(pen_border, dx, dy, dw - 1, dh - 1)
            pen_border.Dispose()

            pen_shadow = Pen(Color.FromArgb(170, 0, 0, 0), 4.0)
            g.DrawLine(pen_shadow, line_x, dy, line_x, dy + dh)
            pen_shadow.Dispose()

            pen_line = Pen(Color.White, 2.0)
            g.DrawLine(pen_line, line_x, dy, line_x, dy + dh)

            cy = dy + dh // 2
            knob_r = 18
            knob_rect = Rectangle(line_x - knob_r, cy - knob_r, knob_r * 2, knob_r * 2)
            br_knob = SolidBrush(Color.FromArgb(16, 185, 129))
            g.FillEllipse(br_knob, knob_rect)
            br_knob.Dispose()
            g.DrawEllipse(pen_line, knob_rect)

            g.DrawLine(pen_line, line_x - 3, cy - 5, line_x - 9, cy)
            g.DrawLine(pen_line, line_x - 9, cy, line_x - 3, cy + 5)
            g.DrawLine(pen_line, line_x + 3, cy - 5, line_x + 9, cy)
            g.DrawLine(pen_line, line_x + 9, cy, line_x + 3, cy + 5)
            pen_line.Dispose()

            br_badge_bg = SolidBrush(Color.FromArgb(195, 15, 23, 42))
            br_badge_after = SolidBrush(Color.FromArgb(210, 5, 150, 105))
            br_white = SolidBrush(Color.White)

            badge_fixed_w = 176
            badge_fixed_h = 26

            if split_px > (badge_fixed_w + 18):
                short_before = u_str(state["before_title"]).split(u"(")[0].strip()
                if not short_before:
                    short_before = u"Scene #1"
                lbl_left_text = u"BEFORE: " + short_before
                if len(lbl_left_text) > 22:
                    lbl_left_text = lbl_left_text[:20] + u".."
                g.FillRectangle(br_badge_bg, dx + 10, dy + 10, badge_fixed_w, badge_fixed_h)
                g.DrawString(lbl_left_text, font_badge, br_white, float(dx + 18), float(dy + 14))

            if (dw - split_px) > (badge_fixed_w + 18):
                lbl_right_text = u"AFTER: AI GENERATION"
                rx = dx + dw - badge_fixed_w - 10
                if rx > line_x + 8:
                    g.FillRectangle(br_badge_after, rx, dy + 10, badge_fixed_w, badge_fixed_h)
                    g.DrawString(lbl_right_text, font_badge, br_white, float(rx + 14), float(dy + 14))

            br_badge_bg.Dispose()
            br_badge_after.Dispose()
            br_white.Dispose()
        finally:
            g.Dispose()

        pct = int(round(ratio * 100))
        lbl_slider_val.Text = u"{}% BEFORE  |  {}% AFTER".format(pct, 100 - pct)
        pic_canvas.Invalidate()

    def _set_split_ratio(new_ratio, sync_trackbar=True):
        r = max(0.0, min(1.0, float(new_ratio)))
        state["split_ratio"] = r
        if sync_trackbar:
            state["updating_slider"] = True
            try:
                slider.Value = int(round(r * 1000))
            except Exception:
                pass
            state["updating_slider"] = False
        _render_split_frame()

    def _update_from_mouse_x(mouse_x):
        dw = max(1, state["draw_w"])
        rel = float(mouse_x - state["draw_x"]) / float(dw)
        _set_split_ratio(rel, sync_trackbar=True)

    def _on_canvas_mouse_down(sender, e):
        if e.Button == MouseButtons.Left:
            state["dragging"] = True
            _update_from_mouse_x(e.X)

    def _on_canvas_mouse_move(sender, e):
        if state["dragging"] or e.Button == MouseButtons.Left:
            _update_from_mouse_x(e.X)

    def _on_canvas_mouse_up(sender, e):
        state["dragging"] = False

    pic_canvas.MouseDown += _on_canvas_mouse_down
    pic_canvas.MouseMove += _on_canvas_mouse_move
    pic_canvas.MouseUp += _on_canvas_mouse_up

    def _on_slider_scroll(sender, args):
        if state["updating_slider"]:
            return
        _set_split_ratio(float(slider.Value) / 1000.0, sync_trackbar=False)

    slider.ValueChanged += _on_slider_scroll

    btn_only_after.Click += lambda s, a: _set_split_ratio(0.0, sync_trackbar=True)
    btn_center_split.Click += lambda s, a: _set_split_ratio(0.5, sync_trackbar=True)
    btn_only_before.Click += lambda s, a: _set_split_ratio(1.0, sync_trackbar=True)

    def _on_input_combo_changed(sender, args):
        idx = cmb_input.SelectedIndex
        if idx < 0 or idx >= len(valid_inputs):
            return
        sel_title, sel_path = valid_inputs[idx]
        if not sel_path or not File.Exists(sel_path):
            return
        new_bmp = load_image_unlocked(sel_path)
        if new_bmp is not None:
            if state["before_orig"] is not None:
                try:
                    state["before_orig"].Dispose()
                except Exception:
                    pass
            state["before_orig"] = new_bmp
            state["before_title"] = sel_title
            state["before_path"] = sel_path
            _rebuild_scaled_cache()
            _render_split_frame()

    cmb_input.SelectedIndexChanged += _on_input_combo_changed

    def _on_pick_custom_compare_file(sender, args):
        dlg = OpenFileDialog()
        dlg.Title = u"Select Before Image for Comparison"
        dlg.Filter = u"Images (*.png;*.jpg;*.jpeg;*.bmp;*.webp)|*.png;*.jpg;*.jpeg;*.bmp;*.webp|All Files (*.*)|*.*"
        if state["before_path"] and File.Exists(state["before_path"]):
            try:
                dlg.InitialDirectory = Path.GetDirectoryName(state["before_path"])
            except Exception:
                pass
        if dlg.ShowDialog() == DialogResult.OK:
            f_path = u_str(dlg.FileName)
            f_label = u"File: " + Path.GetFileName(f_path)
            valid_inputs.append([f_label, f_path])
            cmb_input.Items.Add(f_label)
            cmb_input.SelectedIndex = cmb_input.Items.Count - 1

    btn_add_file.Click += _on_pick_custom_compare_file

    btn_full_before.Click += lambda s, a: show_full_image_window(
        state["before_path"], u"BEFORE: " + state["before_title"], state["before_orig"]
    )
    btn_full_after.Click += lambda s, a: show_full_image_window(
        after_path, u"AFTER: " + after_label, state["after_orig"]
    )

    def _layout_cmp(s=None, a=None):
        cw = form.ClientSize.Width
        ch = form.ClientSize.Height
        if cw < 300 or ch < 300:
            return
        top_h = 50
        bot_h = 82
        canvas_h = max(120, ch - top_h - bot_h)

        pnl_top.Location = Point(0, 0)
        pnl_top.Size = Size(cw, top_h)
        btn_full_after.Location = Point(cw - 16 - 112, 11)
        btn_full_before.Location = Point(btn_full_after.Location.X - 8 - 98, 11)

        avail_left = max(420, btn_full_before.Location.X - 12)
        cmb_w = max(180, min(330, avail_left - 124 - 106 - 190))
        cmb_input.Location = Point(124, 12)
        cmb_input.Size = Size(cmb_w, 26)
        btn_add_file.Location = Point(124 + cmb_w + 8, 11)
        lbl_vs_x = btn_add_file.Location.X + btn_add_file.Width + 12
        lbl_vs.Location = Point(lbl_vs_x, 15)
        lbl_vs.Size = Size(max(120, btn_full_before.Location.X - lbl_vs_x - 8), 22)

        pic_canvas.Location = Point(0, top_h)
        pic_canvas.Size = Size(cw, canvas_h)

        pnl_bottom.Location = Point(0, top_h + canvas_h)
        pnl_bottom.Size = Size(cw, bot_h)

        slider_x = 740
        slider_w = max(180, cw - slider_x - 18)
        slider.Location = Point(slider_x, 7)
        slider.Size = Size(slider_w, 28)

        btn_close.Location = Point(cw - 16 - 156, 40)
        lbl_prompt.Size = Size(max(200, btn_close.Location.X - 28), 34)

        _rebuild_scaled_cache()
        _render_split_frame()

    def _on_cmp_closed(s, a):
        _dispose_scaled_cache()
        for k in ("before_orig", "after_orig", "comp_bmp"):
            if state[k] is not None:
                try:
                    state[k].Dispose()
                except Exception:
                    pass
                state[k] = None

    for _pnl_c in (pnl_top, pnl_bottom):
        for _b_c in _pnl_c.Controls:
            if isinstance(_b_c, Button):
                apply_button_hover(_b_c, _b_c.BackColor, _b_c.FlatAppearance.BorderColor)
    form.Resize += _layout_cmp
    form.FormClosed += _on_cmp_closed
    _layout_cmp()
    form.Show()


# USER INTERFACE
# ==============================================================================
# 8. ГЛАВНОЕ ОКНО СТУДИИ (v3.8 — НАСТРОЙКИ ПРОМПТОВ, ТЕМ И ПОДСКАЗОК КАК В REVIT)
# ==============================================================================

NONE_VIEW_LABEL = u"Select a model view or attach an external file"

# Задержки всплывающих подсказок как в интерфейсе Autodesk Revit (в миллисекундах)
REVIT_TOOLTIP_INITIAL_DELAY_MS = 700    # Время удержания курсора при наведении до появления подсказки (~0.7 сек)
REVIT_TOOLTIP_RESHOW_DELAY_MS = 500     # Задержка при переводе курсора на соседний элемент (~0.5 сек)
REVIT_TOOLTIP_AUTOPOP_DELAY_MS = 20000  # Длительность показа открытой подсказки (20 сек)

# --- БЫСТРАЯ НАСТРОЙКА ТЕКСТА ПРОМПТОВ (ЛЕГКО ПЕРЕКЛЮЧАТЬ В 1 СТРОКУ) ---
# True  -> жирный шрифт (Bold) в полях Prompt и Negative Prompt
# False -> обычный шрифт (Regular) в полях Prompt и Negative Prompt
PROMPT_TEXT_BOLD = False

# Цвета текста для ДНЕВНОЙ (Light) и НОЧНОЙ (Dark) темы (не светлые, с высокой читаемостью):
PROMPT_COLOR_LIGHT = Color.FromArgb(4, 120, 87)        # Изумрудный для дневной темы (#047857)
PROMPT_COLOR_DARK = Color.FromArgb(16, 185, 129)       # Изумрудный для ночной темы (#10B981)
NEG_PROMPT_COLOR_LIGHT = Color.FromArgb(185, 28, 28)   # Рубиново-красный для дневной темы (#B91C1C)
NEG_PROMPT_COLOR_DARK = Color.FromArgb(229, 72, 77)    # Карминно-красный для ночной темы (#E5484D)

# Единый цвет заливки шапки «AI RENDER STUDIO» и акцентных графитовых кнопок («Подключить модели...», «EXIT | ВЫХОД»)
# Вдохновлено Google Material 3 / Autodesk HIG / стальным графитом (между RAL 9007 и Google Slate):
GRAPHITE_BTN_LIGHT = Color.FromArgb(71, 85, 105)       # Стальной графит для дневной темы (#475569)
GRAPHITE_BTN_DARK = Color.FromArgb(51, 65, 85)         # Благородный графит для ночной темы (#334155)
HEADER_BG_LIGHT = GRAPHITE_BTN_LIGHT                   # Цвет шапки в дневной теме = цвету кнопки подключения моделей
HEADER_BG_DARK = GRAPHITE_BTN_DARK                     # Цвет шапки в ночной теме = цвету кнопки подключения моделей


class ChutesRevitStudioForm(Form):
    def __init__(
        self,
        doc,
        revit_invoker,
        init_api_key,
        init_slot1_in,
        init_prompt,
        init_base_url,
        init_out_dir,
        init_max_side,
        init_steps,
        init_slot2_in=None,
        init_slot3_in=None,
    ):
        Form.__init__(self)
        self.doc = doc
        self.revit_invoker = revit_invoker
        self.profiles_data = load_profiles_data()
        self._is_initializing = True
        self._suppress_slot_events = False
        self._syncing_params = False
        self.manual_width_enabled = False

        self.slots = [
            {
                "index": 0,
                "title": u"Scene #1 (Primary)",
                "enabled": False,
                "source_type": "none",
                "view_id": -1,
                "view_obj": None,
                "view_name": u"",
                "file_path": u"",
                "preview_path": u"",
            },
            {
                "index": 1,
                "title": u"Scene #2 (Optional)",
                "enabled": False,
                "source_type": "none",
                "view_id": -1,
                "view_obj": None,
                "view_name": u"",
                "file_path": u"",
                "preview_path": u"",
            },
            {
                "index": 2,
                "title": u"Scene #3 (Optional)",
                "enabled": False,
                "source_type": "none",
                "view_id": -1,
                "view_obj": None,
                "view_name": u"",
                "file_path": u"",
                "preview_path": u"",
            },
        ]

        self.source_image_path = u""
        self.result_image_path = u""
        self.status_message = u"Studio v3.8 ready"
        self.meta_result = {}
        self.execution_succeeded = False

        self.all_views = collect_project_views(doc, include_non_3d=False)
        self.filtered_views = list(self.all_views)
        self.available_models = []
        self.selected_model_info = dict(BUILTIN_CHUTES_IMAGE_MODELS[0])

        self.preview_temp_dir = Path.Combine(Path.GetTempPath(), u"DynamoChutesPreview")
        if not Directory.Exists(self.preview_temp_dir):
            try:
                Directory.CreateDirectory(self.preview_temp_dir)
            except Exception:
                pass

        self.is_dark_mode = bool(self.profiles_data.get("ui_dark_mode", False))
        self._set_palette_colors(self.is_dark_mode)

        self.font_title = Font("Segoe UI", 12.0, FontStyle.Bold)
        self.font_sec = Font("Segoe UI", 9.5, FontStyle.Bold)
        self.font_reg = Font("Segoe UI", 9.0, FontStyle.Regular)
        self.font_prompt = Font("Segoe UI", 9.0, FontStyle.Bold if PROMPT_TEXT_BOLD else FontStyle.Regular)
        self.font_small = Font("Segoe UI", 8.25, FontStyle.Regular)
        self.font_small_bold = Font("Segoe UI", 8.25, FontStyle.Bold)
        self.font_mono = Font("Consolas", 8.5, FontStyle.Regular)

        self.tooltip = ToolTip()
        self.param_tooltip = ToolTip()
        self._active_help_ctrl = None
        self._pending_help_ctrl = None
        self._pending_help_text = u""
        self._param_hover_timer = Timer()
        self._param_hover_timer.Interval = REVIT_TOOLTIP_INITIAL_DELAY_MS
        self._param_hover_timer.Tick += self._on_param_hover_timer_tick
        try:
            self.tooltip.AutoPopDelay = REVIT_TOOLTIP_AUTOPOP_DELAY_MS
            self.tooltip.InitialDelay = REVIT_TOOLTIP_INITIAL_DELAY_MS
            self.tooltip.ReshowDelay = REVIT_TOOLTIP_RESHOW_DELAY_MS
            self.tooltip.ShowAlways = True

            self.param_tooltip.AutoPopDelay = REVIT_TOOLTIP_AUTOPOP_DELAY_MS
            self.param_tooltip.InitialDelay = REVIT_TOOLTIP_INITIAL_DELAY_MS
            self.param_tooltip.ReshowDelay = REVIT_TOOLTIP_RESHOW_DELAY_MS
            self.param_tooltip.ShowAlways = True
        except Exception:
            pass

        self.slot_combos = []
        self.slot_file_btns = []
        self.slot_clear_btns = []
        self.slot_checkboxes = []
        self.slot_pic_boxes = []
        self.slot_placeholders = []

        self._build_ui(
            init_api_key,
            init_slot1_in,
            init_prompt,
            init_base_url,
            init_out_dir,
            init_max_side,
            init_steps,
            init_slot2_in,
            init_slot3_in,
        )
        self._is_initializing = False
        self.progress_bar.Value = 0

    def _set_palette_colors(self, is_dark):
        self.is_dark_mode = bool(is_dark)
        self.col_dark = Color.FromArgb(30, 41, 59)
        self.col_header_bg = HEADER_BG_DARK if is_dark else HEADER_BG_LIGHT
        self.col_emerald = Color.FromArgb(16, 185, 129)
        self.col_emerald_dark = Color.FromArgb(5, 150, 105)
        self.col_emerald_soft_bg = Color.FromArgb(6, 78, 59) if is_dark else Color.FromArgb(209, 250, 229)
        self.col_emerald_soft_fg = Color.FromArgb(52, 211, 153) if is_dark else Color.FromArgb(4, 120, 87)
        self.col_emerald_soft_brd = Color.FromArgb(16, 185, 129) if is_dark else Color.FromArgb(110, 231, 183)
        self.col_success = Color.FromArgb(34, 197, 94) if is_dark else Color.FromArgb(22, 163, 74)
        self.col_prompt_fg = PROMPT_COLOR_DARK if is_dark else PROMPT_COLOR_LIGHT
        self.col_neg_prompt_fg = NEG_PROMPT_COLOR_DARK if is_dark else NEG_PROMPT_COLOR_LIGHT
        if is_dark:
            self.col_bg = Color.FromArgb(22, 27, 36)
            self.col_card = Color.FromArgb(32, 39, 52)
            self.col_input_bg = Color.FromArgb(24, 30, 42)
            self.col_log_bg = Color.FromArgb(18, 23, 33)
            self.col_sec_hdr = Color.FromArgb(241, 245, 249)
            self.col_text = Color.FromArgb(226, 232, 240)
            self.col_muted = Color.FromArgb(148, 163, 184)
            self.col_border = Color.FromArgb(56, 68, 89)
            self.col_accent = Color.FromArgb(96, 165, 250)
            self.col_accent_soft = Color.FromArgb(30, 58, 95)
            self.col_btn_dark = GRAPHITE_BTN_DARK
            self.col_slot_active = Color.FromArgb(25, 32, 44)
            self.col_slot_inactive = Color.FromArgb(19, 24, 34)
        else:
            self.col_bg = Color.FromArgb(246, 248, 250)
            self.col_card = Color.FromArgb(255, 255, 255)
            self.col_input_bg = Color.FromArgb(255, 255, 255)
            self.col_log_bg = Color.FromArgb(248, 250, 252)
            self.col_sec_hdr = Color.FromArgb(30, 41, 59)
            self.col_text = Color.FromArgb(30, 41, 59)
            self.col_muted = Color.FromArgb(100, 116, 139)
            self.col_border = Color.FromArgb(226, 232, 240)
            self.col_accent = Color.FromArgb(37, 99, 235)
            self.col_accent_soft = Color.FromArgb(239, 246, 255)
            self.col_btn_dark = GRAPHITE_BTN_LIGHT
            self.col_slot_active = Color.FromArgb(241, 245, 249)
            self.col_slot_inactive = Color.FromArgb(226, 232, 240)

    def _style_button_by_role(self, btn):
        if btn is None:
            return
        role = u_str(getattr(btn, "Tag", u"surface"))
        if role == u"accent_soft":
            bg, fg = self.col_accent_soft, self.col_accent
            brd = self.col_border if self.is_dark_mode else self.col_accent_soft
        elif role == u"emerald_soft":
            bg, fg, brd = self.col_emerald_soft_bg, self.col_emerald_soft_fg, self.col_emerald_soft_brd
        elif role == u"emerald":
            bg, fg, brd = self.col_emerald, Color.White, self.col_emerald_dark
        elif role == u"primary_dark":
            bg, fg = self.col_btn_dark, Color.White
            brd = Color.FromArgb(82, 98, 122) if self.is_dark_mode else Color.FromArgb(51, 65, 85)
        elif role == u"surface_accent":
            bg, fg, brd = self.col_card, self.col_accent, self.col_border
        elif role == u"surface_muted":
            bg, fg, brd = self.col_card, self.col_muted, self.col_border
        elif role == u"header_theme":
            bg = Color.FromArgb(38, 49, 66) if self.is_dark_mode else Color.FromArgb(55, 68, 87)
            fg = Color.FromArgb(241, 245, 249)
            brd = Color.FromArgb(120, 136, 159)
        else:
            bg, fg, brd = self.col_card, self.col_text, self.col_border
        btn.ForeColor = fg
        apply_button_hover(btn, bg, brd)

    def _create_card(self, x, y, w, h):
        pnl = Panel()
        pnl.Location = Point(x, y)
        pnl.Size = Size(w, h)
        pnl.BackColor = self.col_card
        pnl.BorderStyle = BorderStyle.FixedSingle
        self.Controls.Add(pnl)
        return pnl

    def _create_button(self, parent, text, x, y, w, h, bg_color, fg_color, bold=False, role=None):
        btn = Button()
        btn.Text = text
        btn.Location = Point(x, y)
        btn.Size = Size(w, h)
        btn.FlatStyle = FlatStyle.Flat
        btn.FlatAppearance.BorderSize = 1
        btn.Font = self.font_sec if bold else self.font_reg
        btn.Cursor = Cursors.Hand
        try:
            btn.Padding = Padding(0)
            btn.UseMnemonic = False
            btn.UseCompatibleTextRendering = False
        except Exception:
            pass
        if role is None:
            if bg_color == self.col_accent_soft:
                role = u"accent_soft"
            elif bg_color == self.col_emerald:
                role = u"emerald"
            elif bg_color == self.col_dark or bg_color == self.col_btn_dark:
                role = u"primary_dark"
            elif bg_color == self.col_card and fg_color == self.col_accent:
                role = u"surface_accent"
            elif bg_color == self.col_card and fg_color == self.col_muted:
                role = u"surface_muted"
            else:
                role = u"surface"
        btn.Tag = role
        self._style_button_by_role(btn)
        parent.Controls.Add(btn)
        return btn

    def _on_param_hover_timer_tick(self, sender, args):
        """Показывает подсказку параметра после удержания курсора (как в GUI Revit)."""
        try:
            self._param_hover_timer.Stop()
        except Exception:
            pass
        target_ctrl = getattr(self, "_pending_help_ctrl", None)
        target_text = getattr(self, "_pending_help_text", u"")
        if target_ctrl is not None and target_text:
            self._show_param_help_for(target_ctrl, target_text)

    def _hide_active_param_help(self, sender=None, args=None):
        """Мгновенно останавливает таймер ожидания и скрывает открытую подсказку параметра."""
        try:
            if hasattr(self, "_param_hover_timer") and self._param_hover_timer is not None:
                self._param_hover_timer.Stop()
        except Exception:
            pass
        pend_ctrl = getattr(self, "_pending_help_ctrl", None)
        self._pending_help_ctrl = None
        self._pending_help_text = u""
        if pend_ctrl is not None:
            try:
                pend_ctrl.ForeColor = self.col_text
            except Exception:
                pass
        prev_ctrl = getattr(self, "_active_help_ctrl", None)
        self._active_help_ctrl = None
        if prev_ctrl is not None:
            try:
                self.param_tooltip.Hide(prev_ctrl)
            except Exception:
                pass
            try:
                prev_ctrl.ForeColor = self.col_text
            except Exception:
                pass

    def _show_param_help_for(self, lbl_ctrl, help_text):
        """Скрывает предыдущую подсказку и показывает новую в стороне от колонки подписей."""
        if lbl_ctrl is None:
            return
        prev_ctrl = getattr(self, "_active_help_ctrl", None)
        if prev_ctrl is not None:
            try:
                self.param_tooltip.Hide(prev_ctrl)
            except Exception:
                pass
            if prev_ctrl is not lbl_ctrl:
                try:
                    prev_ctrl.ForeColor = self.col_text
                except Exception:
                    pass
        self._active_help_ctrl = lbl_ctrl
        try:
            lbl_ctrl.ForeColor = self.col_accent
        except Exception:
            pass
        try:
            # Показываем правее подписи и выше ряда ползунков, чтобы не перекрывать соседние слова Steps / Seed
            self.param_tooltip.Show(
                help_text,
                lbl_ctrl,
                int(lbl_ctrl.Width) + 6,
                -96,
                REVIT_TOOLTIP_AUTOPOP_DELAY_MS,
            )
        except Exception:
            pass

    def _bind_param_help(self, lbl_ctrl, related_ctrls, help_text):
        """Делает подпись параметра интерактивной: при наведении ждёт задержку как в Revit GUI (700 мс), при клике открывает сразу, при уводе скрывает."""
        if lbl_ctrl is None:
            return
        try:
            lbl_ctrl.Cursor = Cursors.Hand
        except Exception:
            pass
        for rc in (related_ctrls or []):
            if rc is not None:
                try:
                    self.tooltip.SetToolTip(rc, help_text)
                    rc.MouseDown += self._hide_active_param_help
                except Exception:
                    pass

        def _on_enter(s, a):
            prev_ctrl = getattr(self, "_active_help_ctrl", None)
            if prev_ctrl is not None and prev_ctrl is not lbl_ctrl:
                self._hide_active_param_help()
            self._pending_help_ctrl = lbl_ctrl
            self._pending_help_text = help_text
            try:
                lbl_ctrl.ForeColor = self.col_accent
            except Exception:
                pass
            try:
                self._param_hover_timer.Stop()
                self._param_hover_timer.Start()
            except Exception:
                self._show_param_help_for(lbl_ctrl, help_text)

        def _on_leave(s, a):
            self._hide_active_param_help()

        def _on_click(s, a):
            try:
                self._param_hover_timer.Stop()
            except Exception:
                pass
            self._show_param_help_for(lbl_ctrl, help_text)

        lbl_ctrl.MouseEnter += _on_enter
        lbl_ctrl.MouseLeave += _on_leave
        lbl_ctrl.Click += _on_click

    def _build_ui(
        self,
        init_api_key,
        init_slot1_in,
        init_prompt,
        init_base_url,
        init_out_dir,
        init_max_side,
        init_steps,
        init_slot2_in,
        init_slot3_in,
    ):
        self.Text = u"AI Render Studio"
        self.Size = Size(1280, 965)
        self.MinimumSize = Size(1080, 885)
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = True
        self.MinimizeBox = True
        self.BackColor = self.col_bg

        # --- ВЕРХНЯЯ ПАНЕЛЬ (ШАПКА) ---
        self.pnl_header = Panel()
        self.pnl_header.Location = Point(0, 0)
        self.pnl_header.Size = Size(1280, 48)
        self.pnl_header.BackColor = self.col_header_bg
        self.Controls.Add(self.pnl_header)

        self.lbl_app_title = Label()
        self.lbl_app_title.Text = u"AI RENDER STUDIO"
        self.lbl_app_title.Location = Point(20, 12)
        self.lbl_app_title.Size = Size(520, 24)
        self.lbl_app_title.Font = self.font_title
        self.lbl_app_title.ForeColor = Color.White
        self.pnl_header.Controls.Add(self.lbl_app_title)

        self.KeyPreview = True
        self.lbl_app_sub = Label()
        self.lbl_app_sub.Text = u"v 3.8"
        self.lbl_app_sub.Location = Point(540, 14)
        self.lbl_app_sub.Size = Size(580, 20)
        self.lbl_app_sub.Font = self.font_reg
        self.lbl_app_sub.ForeColor = Color.FromArgb(203, 213, 225)
        self.lbl_app_sub.TextAlign = ContentAlignment.MiddleRight
        self.pnl_header.Controls.Add(self.lbl_app_sub)

        self.btn_theme_toggle = self._create_button(
            self.pnl_header,
            u"Theme: Dark" if self.is_dark_mode else u"Theme: Light",
            1136,
            11,
            110,
            26,
            self.col_dark,
            Color.White,
            role=u"header_theme",
        )
        self.btn_theme_toggle.Font = self.font_small_bold
        self.btn_theme_toggle.Click += self._on_toggle_theme
        self.tooltip.SetToolTip(
            self.btn_theme_toggle,
            u"Переключение дневной (Light) и ночной (Dark) темы интерфейса (сохраняется в профиле)",
        )

        # ======================================================================
        # КАРТОЧКА 1 (СЛЕВА ВВЕРХУ): ПРОФИЛЬ, BASE URL И API KEY
        # ======================================================================
        self.card_conn = self._create_card(16, 60, 580, 202)

        self.lbl_sec1 = Label()
        self.lbl_sec1.Text = u"I. AI MODEL PROVIDER"
        self.lbl_sec1.Location = Point(14, 10)
        self.lbl_sec1.Size = Size(540, 20)
        self.lbl_sec1.Font = self.font_sec
        self.lbl_sec1.ForeColor = self.col_dark
        self.card_conn.Controls.Add(self.lbl_sec1)

        lbl_prof = Label()
        lbl_prof.Text = u"Profile:"
        lbl_prof.Location = Point(14, 38)
        lbl_prof.Size = Size(70, 22)
        lbl_prof.Font = self.font_reg
        lbl_prof.ForeColor = self.col_muted
        self.card_conn.Controls.Add(lbl_prof)

        self.cmb_profile = ComboBox()
        self.cmb_profile.Location = Point(90, 35)
        self.cmb_profile.Size = Size(265, 24)
        self.cmb_profile.Font = self.font_reg
        self.cmb_profile.FlatStyle = FlatStyle.Popup if self.is_dark_mode else FlatStyle.Standard
        self.cmb_profile.DropDownStyle = ComboBoxStyle.DropDown
        self.cmb_profile.SelectedIndexChanged += self._on_profile_selected
        self.card_conn.Controls.Add(self.cmb_profile)

        self.btn_save_prof = self._create_button(
            self.card_conn, u"Save", 362, 34, 96, 26, self.col_accent_soft, self.col_accent
        )
        self.btn_save_prof.Click += self._on_save_profile
        self.tooltip.SetToolTip(
            self.btn_save_prof,
            u"Сохранить настройки текущего профиля (Base URL, API Key и свои модели)",
        )

        self.btn_del_prof = self._create_button(
            self.card_conn, u"Delete", 464, 34, 80, 26, self.col_card, self.col_muted
        )
        self.btn_del_prof.Click += self._on_delete_profile
        self.tooltip.SetToolTip(
            self.btn_del_prof,
            u"Удалить выбранный профиль из списка сохранённых профилей",
        )

        lbl_url = Label()
        lbl_url.Text = u"Base URL:"
        lbl_url.Location = Point(14, 72)
        lbl_url.Size = Size(70, 22)
        lbl_url.Font = self.font_reg
        lbl_url.ForeColor = self.col_muted
        self.card_conn.Controls.Add(lbl_url)

        self.txt_base_url = TextBox()
        self.txt_base_url.Location = Point(90, 70)
        self.txt_base_url.Size = Size(454, 24)
        self.txt_base_url.Font = self.font_reg
        self.txt_base_url.Text = u_str(init_base_url or u"https://api.chutes.ai")
        self.card_conn.Controls.Add(self.txt_base_url)

        lbl_key = Label()
        lbl_key.Text = u"API Key:"
        lbl_key.Location = Point(14, 106)
        lbl_key.Size = Size(70, 22)
        lbl_key.Font = self.font_reg
        lbl_key.ForeColor = self.col_muted
        self.card_conn.Controls.Add(lbl_key)

        self.txt_api_key = TextBox()
        self.txt_api_key.Location = Point(90, 104)
        self.txt_api_key.Size = Size(374, 24)
        self.txt_api_key.Font = self.font_reg
        self.txt_api_key.UseSystemPasswordChar = True
        self.card_conn.Controls.Add(self.txt_api_key)

        self.btn_toggle_key = self._create_button(
            self.card_conn, u"Show", 470, 103, 74, 25, self.col_card, self.col_muted
        )
        self.btn_toggle_key.Font = self.font_small
        self.btn_toggle_key.Click += self._on_toggle_api_key

        self.btn_fetch_models = self._create_button(
            self.card_conn,
            u"Connect / Refresh Provider Models —>",
            14,
            139,
            530,
            34,
            self.col_dark,
            Color.White,
            bold=True,
        )
        self.btn_fetch_models.Click += self._on_fetch_models_click

        self.lbl_prof_path = Label()
        self.lbl_prof_path.Text = u"Profiles: " + get_profiles_file_path()
        self.lbl_prof_path.Location = Point(14, 178)
        self.lbl_prof_path.Size = Size(530, 16)
        self.lbl_prof_path.Font = self.font_small
        self.lbl_prof_path.ForeColor = self.col_muted
        self.card_conn.Controls.Add(self.lbl_prof_path)

        # ======================================================================
        # КАРТОЧКА 2 (СПРАВА ВВЕРХУ): МОДЕЛИ ГЕНЕРАЦИИ + РУЧНОЕ ДОБАВЛЕНИЕ В ПРОФИЛЬ
        # ======================================================================
        self.card_models = self._create_card(610, 60, 636, 202)

        self.lbl_sec2 = Label()
        self.lbl_sec2.Text = u"II. AI MODEL"
        self.lbl_sec2.Location = Point(14, 8)
        self.lbl_sec2.Size = Size(420, 20)
        self.lbl_sec2.Font = self.font_sec
        self.lbl_sec2.ForeColor = self.col_dark
        self.card_models.Controls.Add(self.lbl_sec2)

        self.lbl_models_status = Label()
        self.lbl_models_status.Text = u"Ready"
        self.lbl_models_status.Location = Point(440, 9)
        self.lbl_models_status.Size = Size(180, 18)
        self.lbl_models_status.Font = self.font_small
        self.lbl_models_status.ForeColor = self.col_accent
        self.lbl_models_status.TextAlign = ContentAlignment.MiddleRight
        self.card_models.Controls.Add(self.lbl_models_status)

        self.lst_models = ListBox()
        self.lst_models.Location = Point(14, 30)
        self.lst_models.Size = Size(606, 82)
        self.lst_models.Font = self.font_reg
        self.lst_models.BorderStyle = BorderStyle.FixedSingle
        self.lst_models.SelectedIndexChanged += self._on_model_selected
        self.card_models.Controls.Add(self.lst_models)

        self.lbl_custom_m = Label()
        self.lbl_custom_m.Text = u"Add Model:"
        self.lbl_custom_m.Location = Point(14, 118)
        self.lbl_custom_m.Size = Size(82, 20)
        self.lbl_custom_m.Font = self.font_small_bold
        self.lbl_custom_m.ForeColor = self.col_text
        self.card_models.Controls.Add(self.lbl_custom_m)

        self.txt_custom_model = TextBox()
        self.txt_custom_model.Location = Point(98, 115)
        self.txt_custom_model.Size = Size(320, 22)
        self.txt_custom_model.Font = self.font_small
        self.card_models.Controls.Add(self.txt_custom_model)

        self._bind_param_help(
            self.lbl_custom_m,
            [self.txt_custom_model],
            (
                u"Позволяет добавить любую модель Chutes.ai или внешнего провайдера\n"
                u"› Введите имя модели и нажмите + To Profile\n"
                u"› Сохранённые модели отображаются в списке со значком ★"
            ),
        )

        self.btn_add_model = self._create_button(
            self.card_models, u"+ To Profile", 424, 114, 102, 24, self.col_accent_soft, self.col_accent
        )
        self.btn_add_model.Font = self.font_small_bold
        self.btn_add_model.Click += self._on_add_custom_model_click
        self.tooltip.SetToolTip(
            self.btn_add_model,
            u"Сохранить модель из поля Add Model в текущий профиль",
        )

        self.btn_del_model = self._create_button(
            self.card_models, u"Remove", 532, 114, 88, 24, self.col_card, self.col_muted
        )
        self.btn_del_model.Font = self.font_small
        self.btn_del_model.Click += self._on_remove_custom_model_click
        self.tooltip.SetToolTip(
            self.btn_del_model,
            u"Удалить выбранную пользовательскую модель (★) из текущего профиля",
        )

        self.lbl_ep = Label()
        self.lbl_ep.Text = u"Endpoint:"
        self.lbl_ep.Location = Point(14, 146)
        self.lbl_ep.Size = Size(82, 20)
        self.lbl_ep.Font = self.font_small_bold
        self.lbl_ep.ForeColor = self.col_text
        self.card_models.Controls.Add(self.lbl_ep)

        self.txt_endpoint = TextBox()
        self.txt_endpoint.Location = Point(98, 143)
        self.txt_endpoint.Size = Size(522, 22)
        self.txt_endpoint.Font = self.font_small
        self.txt_endpoint.Text = BUILTIN_CHUTES_IMAGE_MODELS[0]["endpoint"]
        self.card_models.Controls.Add(self.txt_endpoint)

        self._bind_param_help(
            self.lbl_ep,
            [self.txt_endpoint],
            (
                u"Адрес, на который приложение отправляет запрос генерации изображения\n"
                u"› Подставляется автоматически при выборе модели в списке выше\n"
                u"› Можно изменить вручную для своей модели или локального сервера"
            ),
        )

        self.chk_send_image = CheckBox()
        self.chk_send_image.Text = u"Send Scene Images [Base64]"
        self.chk_send_image.Location = Point(14, 171)
        self.chk_send_image.Size = Size(310, 22)
        self.chk_send_image.Font = self.font_small
        self.chk_send_image.ForeColor = self.col_text
        self.chk_send_image.Checked = True
        self.tooltip.SetToolTip(
            self.chk_send_image,
            (
                u"Send Scene Images [Base64] (Передача входных кадров в поле image_b64s)\n"
                u"Кодирует активные виды и файлы из Scene #1..#3 в Base64 и передаёт их модели\n"
                u"› Включено: для моделей редактирования по кадру (Qwen-Image-Edit-2511)\n"
                u"› Выключено: генерация только по тексту промпта (Qwen-Image-2512, z-image-turbo, imageclassic)"
            ),
        )
        self.card_models.Controls.Add(self.chk_send_image)

        self.chk_retry_busy = CheckBox()
        self.chk_retry_busy.Text = u"AutoReconnect [x4]"
        self.chk_retry_busy.Location = Point(330, 171)
        self.chk_retry_busy.Size = Size(292, 22)
        self.chk_retry_busy.Font = self.font_small
        self.chk_retry_busy.ForeColor = self.col_accent
        self.chk_retry_busy.Checked = True
        self.tooltip.SetToolTip(
            self.chk_retry_busy,
            u"При ошибке занятого сервера (HTTP 500: No infrastructure available) автоматически повторяет запрос до 4 раз с паузой 2.5 сек",
        )
        self.card_models.Controls.Add(self.chk_retry_busy)

        # ======================================================================
        # КАРТОЧКА 3 (СЛЕВА В СЕРЕДИНЕ): 3 СЛОТА + ПРОМПТЫ + ПАРАМЕТРЫ
        # ======================================================================
        self.card_view = self._create_card(16, 272, 580, 470)

        self.lbl_sec3 = Label()
        self.lbl_sec3.Text = u"III. MODEL INPUTS"
        self.lbl_sec3.Location = Point(14, 8)
        self.lbl_sec3.Size = Size(540, 20)
        self.lbl_sec3.Font = self.font_sec
        self.lbl_sec3.ForeColor = self.col_dark
        self.card_view.Controls.Add(self.lbl_sec3)

        self.lbl_search_v = Label()
        self.lbl_search_v.Text = u"Search:"
        self.lbl_search_v.Location = Point(14, 35)
        self.lbl_search_v.Size = Size(76, 20)
        self.lbl_search_v.Font = self.font_small_bold
        self.lbl_search_v.ForeColor = self.col_muted
        self.card_view.Controls.Add(self.lbl_search_v)

        self.txt_view_search = TextBox()
        self.txt_view_search.Location = Point(94, 32)
        self.txt_view_search.Size = Size(298, 24)
        self.txt_view_search.Font = self.font_reg
        self.txt_view_search.TextChanged += self._on_view_search_changed
        self.tooltip.SetToolTip(
            self.txt_view_search,
            u"Введите часть названия вида для быстрого фильтра списков Scene #1..#3",
        )
        self.card_view.Controls.Add(self.txt_view_search)

        self.btn_clear_search = self._create_button(
            self.card_view, u"Reset", 396, 31, 56, 25, self.col_card, self.col_muted
        )
        self.btn_clear_search.Font = self.font_small
        self.btn_clear_search.Click += self._on_clear_view_search
        self.tooltip.SetToolTip(self.btn_clear_search, u"Очистить строку поиска видов")

        self.chk_all_views = CheckBox()
        self.chk_all_views.Text = u"2D View"
        self.chk_all_views.Location = Point(458, 34)
        self.chk_all_views.Size = Size(88, 20)
        self.chk_all_views.Font = self.font_small
        self.chk_all_views.ForeColor = self.col_muted
        self.chk_all_views.CheckedChanged += self._on_toggle_all_views
        self.tooltip.SetToolTip(
            self.chk_all_views,
            u"Показать в выпадающих списках Scene #1..#3 также 2D-виды проекта (планы, фасады, разрезы)",
        )
        self.card_view.Controls.Add(self.chk_all_views)

        self.slot_row_labels = []
        slot_short_names = [u"Scene #1:", u"Scene #2:", u"Scene #3:"]
        for s_idx in range(3):
            row_y = 62 + s_idx * 28
            lbl_s = Label()
            lbl_s.Text = slot_short_names[s_idx]
            lbl_s.Location = Point(14, row_y + 3)
            lbl_s.Size = Size(76, 20)
            lbl_s.Font = self.font_small_bold
            lbl_s.ForeColor = self.col_muted
            self.card_view.Controls.Add(lbl_s)
            self.slot_row_labels.append(lbl_s)

            cmb_s = ComboBox()
            cmb_s.Location = Point(94, row_y)
            cmb_s.Size = Size(358, 24)
            cmb_s.Font = self.font_reg
            cmb_s.FlatStyle = FlatStyle.Popup if self.is_dark_mode else FlatStyle.Standard
            cmb_s.DrawMode = DrawMode.OwnerDrawFixed if self.is_dark_mode else DrawMode.Normal
            cmb_s.ItemHeight = 18
            cmb_s.DropDownStyle = ComboBoxStyle.DropDownList
            cmb_s.DrawItem += self._on_combo_draw_item
            cmb_s.SelectedIndexChanged += self._make_slot_combo_handler(s_idx)
            self.tooltip.SetToolTip(
                cmb_s,
                u"Выберите вид Revit для Scene #{} или нажмите File... справа".format(s_idx + 1),
            )
            self.card_view.Controls.Add(cmb_s)
            self.slot_combos.append(cmb_s)

            btn_f = self._create_button(
                self.card_view,
                u"File...",
                458,
                row_y - 1,
                58,
                25,
                self.col_accent_soft,
                self.col_accent,
            )
            btn_f.Font = self.font_small
            btn_f.Click += self._make_slot_file_handler(s_idx)
            self.tooltip.SetToolTip(btn_f, u"Выбрать готовый графический файл с диска для Scene #{}".format(s_idx + 1))
            self.slot_file_btns.append(btn_f)

            btn_clr = self._create_button(
                self.card_view,
                u"✕",
                520,
                row_y - 1,
                26,
                25,
                self.col_card,
                self.col_muted,
            )
            btn_clr.Font = self.font_small
            btn_clr.Click += self._make_slot_clear_handler(s_idx)
            self.tooltip.SetToolTip(btn_clr, u"Очистить и отключить Scene #{}".format(s_idx + 1))
            self.slot_clear_btns.append(btn_clr)

        # --- Prompt (слева) и Negative Prompt (справа) + Sys.Prompt + +Template ---
        self.lbl_pr = Label()
        self.lbl_pr.Text = u"Prompt:"
        self.lbl_pr.Location = Point(14, 150)
        self.lbl_pr.Size = Size(56, 20)
        self.lbl_pr.Font = self.font_small_bold
        self.lbl_pr.ForeColor = self.col_text
        self.tooltip.SetToolTip(
            self.lbl_pr,
            u"Основной промпт: опишите желаемый стиль, материалы фасада, освещение и окружение",
        )
        self.card_view.Controls.Add(self.lbl_pr)

        self.btn_sys_prompt = self._create_button(
            self.card_view, u"Sys.Prompt [off]", 72, 145, 118, 25, self.col_card, self.col_text
        )
        self.btn_sys_prompt.Font = self.font_small
        self.btn_sys_prompt.Click += self._on_sys_prompt_click
        self.tooltip.SetToolTip(
            self.btn_sys_prompt,
            u"Настроить системный промпт (правила сохранения 3D-геометрии и перспективы кадра)",
        )

        self.btn_pos_tpl = self._create_button(
            self.card_view, u"+Template", 194, 145, 88, 25, self.col_accent_soft, self.col_accent
        )
        self.btn_pos_tpl.Font = self.font_small
        self.btn_pos_tpl.Click += self._on_pos_templates_click
        self.tooltip.SetToolTip(self.btn_pos_tpl, u"Открыть библиотеку шаблонов для основного промпта")

        self.lbl_neg_pr = Label()
        self.lbl_neg_pr.Text = u"Negative Prompt:"
        self.lbl_neg_pr.Location = Point(292, 150)
        self.lbl_neg_pr.Size = Size(125, 20)
        self.lbl_neg_pr.Font = self.font_small_bold
        self.lbl_neg_pr.ForeColor = self.col_muted
        self.tooltip.SetToolTip(
            self.lbl_neg_pr,
            u"Негативный промпт: укажите, чего не должно быть на рендере (искажения геометрии, размытие, лишние объекты)",
        )
        self.card_view.Controls.Add(self.lbl_neg_pr)

        self.btn_neg_tpl = self._create_button(
            self.card_view, u"+Template", 458, 145, 88, 25, self.col_accent_soft, self.col_accent
        )
        self.btn_neg_tpl.Font = self.font_small
        self.btn_neg_tpl.Click += self._on_neg_templates_click
        self.tooltip.SetToolTip(self.btn_neg_tpl, u"Открыть библиотеку шаблонов для негативного промпта")

        self.txt_prompt = TextBox()
        self.txt_prompt.Location = Point(14, 173)
        self.txt_prompt.Size = Size(268, 96)
        self.txt_prompt.Multiline = True
        self.txt_prompt.ScrollBars = ScrollBars.Vertical
        self.txt_prompt.Font = self.font_prompt
        self.txt_prompt.ForeColor = self.col_prompt_fg
        self.txt_prompt.Text = u_str(
            init_prompt
            or u"Convert this 3D CAD view into a photorealistic architectural render, preserve exact building contours and geometry, glass and concrete facade, sunny day"
        )
        self.card_view.Controls.Add(self.txt_prompt)

        self.txt_neg_prompt = TextBox()
        self.txt_neg_prompt.Location = Point(292, 173)
        self.txt_neg_prompt.Size = Size(268, 96)
        self.txt_neg_prompt.Multiline = True
        self.txt_neg_prompt.ScrollBars = ScrollBars.Vertical
        self.txt_neg_prompt.Font = self.font_prompt
        self.txt_neg_prompt.ForeColor = self.col_neg_prompt_fg
        self.txt_neg_prompt.Text = u""
        self.tooltip.SetToolTip(
            self.txt_neg_prompt,
            u"Необязательно: перечислите нежелательные детали или выберите готовый шаблон по кнопке +Template",
        )
        self.card_view.Controls.Add(self.txt_neg_prompt)

        # --- РЯД РАЗМЕРОВ: Height + Width + Кнопка Auto Width (размером как Random Seed) ---
        self.lbl_sz = Label()
        self.lbl_sz.Text = u"Height:"
        self.lbl_sz.Location = Point(14, 280)
        self.lbl_sz.Size = Size(54, 22)
        self.lbl_sz.Font = self.font_small_bold
        self.lbl_sz.ForeColor = self.col_text
        self.card_view.Controls.Add(self.lbl_sz)

        self.num_size = NumericUpDown()
        self.num_size.Location = Point(70, 278)
        self.num_size.Size = Size(76, 24)
        self.num_size.Minimum = to_decimal(512)
        self.num_size.Maximum = to_decimal(2048)
        self.num_size.Increment = to_decimal(64)
        self.num_size.Value = to_decimal(max(512, min(2048, int(init_max_side or 1024))))
        self.num_size.Font = self.font_reg
        self.num_size.ValueChanged += self._on_height_value_changed
        self.card_view.Controls.Add(self.num_size)

        self.lbl_width = Label()
        self.lbl_width.Text = u"Width:"
        self.lbl_width.Location = Point(156, 280)
        self.lbl_width.Size = Size(48, 22)
        self.lbl_width.Font = self.font_small_bold
        self.lbl_width.ForeColor = self.col_text
        self.card_view.Controls.Add(self.lbl_width)

        self.num_width = NumericUpDown()
        self.num_width.Location = Point(206, 278)
        self.num_width.Size = Size(76, 24)
        self.num_width.Minimum = to_decimal(512)
        self.num_width.Maximum = to_decimal(2048)
        self.num_width.Increment = to_decimal(64)
        self.num_width.Value = to_decimal(max(512, min(2048, int(init_max_side or 1024))))
        self.num_width.Font = self.font_reg
        self.num_width.Enabled = False
        self.card_view.Controls.Add(self.num_width)

        self._bind_param_help(
            self.lbl_sz,
            [self.num_size],
            (
                u"Height (Высота / базовый размер рендера в пикселях, 512–2048, шаг 64)\n"
                u"Определяет целевое разрешение выходного изображения\n"
                u"› В режиме Auto Width задаёт большую сторону с сохранением пропорций вида Revit\n"
                u"› В режиме Manual W×H задаёт точную высоту картинки в пикселях"
            ),
        )
        self._bind_param_help(
            self.lbl_width,
            [self.num_width],
            (
                u"Width (Ширина рендера в пикселях, 512–2048, шаг 64)\n"
                u"В режиме Auto Width рассчитывается автоматически по пропорциям кадра Scene #1\n"
                u"› Нажмите кнопку Auto Width справа, чтобы разблокировать ручной ввод ширины"
            ),
        )

        self.btn_toggle_width = self._create_button(
            self.card_view, u"Auto Width", 292, 277, 118, 25, self.col_accent_soft, self.col_accent
        )
        self.btn_toggle_width.Font = self.font_small_bold
        self.btn_toggle_width.Click += self._on_toggle_manual_width
        self.tooltip.SetToolTip(
            self.btn_toggle_width,
            (
                u"Переключение между автоматическим расчётом ширины по пропорциям кадра (Auto Width) и ручным вводом (Manual W×H)"
            ),
        )

        # --- 3 РЯДА ПОЛЗУНКОВ ДРУГ ПОД ДРУГОМ: Edit Guidance, Steps, Seed ---
        self.lbl_cfg = Label()
        self.lbl_cfg.Text = u"Edit Guidance:"
        self.lbl_cfg.Location = Point(14, 310)
        self.lbl_cfg.Size = Size(88, 22)
        self.lbl_cfg.Font = self.font_small_bold
        self.lbl_cfg.ForeColor = self.col_text
        self.card_view.Controls.Add(self.lbl_cfg)

        self.trk_guidance = TrackBar()
        self.trk_guidance.Location = Point(104, 308)
        self.trk_guidance.Size = Size(224, 24)
        self.trk_guidance.Minimum = 0
        self.trk_guidance.Maximum = 200
        self.trk_guidance.Value = 10
        self.trk_guidance.TickStyle = getattr(TickStyle, "None", TickStyle.BottomRight)
        self.trk_guidance.AutoSize = False
        self.trk_guidance.ValueChanged += self._on_trk_guidance_changed
        self.card_view.Controls.Add(self.trk_guidance)

        self.num_guidance = NumericUpDown()
        self.num_guidance.Location = Point(334, 308)
        self.num_guidance.Size = Size(86, 24)
        self.num_guidance.DecimalPlaces = 1
        self.num_guidance.Minimum = to_decimal(0.0)
        self.num_guidance.Maximum = to_decimal(20.0)
        self.num_guidance.Increment = to_decimal(0.5)
        self.num_guidance.Value = to_decimal(1.0)
        self.num_guidance.Font = self.font_reg
        self.num_guidance.ValueChanged += self._on_num_guidance_changed
        self.card_view.Controls.Add(self.num_guidance)

        self.lbl_st = Label()
        self.lbl_st.Text = u"Steps:"
        self.lbl_st.Location = Point(14, 338)
        self.lbl_st.Size = Size(88, 22)
        self.lbl_st.Font = self.font_small_bold
        self.lbl_st.ForeColor = self.col_text
        self.card_view.Controls.Add(self.lbl_st)

        init_steps_clamped = max(1, min(100, int(init_steps or 4)))
        self.trk_steps = TrackBar()
        self.trk_steps.Location = Point(104, 336)
        self.trk_steps.Size = Size(224, 24)
        self.trk_steps.Minimum = 1
        self.trk_steps.Maximum = 100
        self.trk_steps.Value = init_steps_clamped
        self.trk_steps.TickStyle = getattr(TickStyle, "None", TickStyle.BottomRight)
        self.trk_steps.AutoSize = False
        self.trk_steps.ValueChanged += self._on_trk_steps_changed
        self.card_view.Controls.Add(self.trk_steps)

        self.num_steps = NumericUpDown()
        self.num_steps.Location = Point(334, 336)
        self.num_steps.Size = Size(86, 24)
        self.num_steps.Minimum = to_decimal(1)
        self.num_steps.Maximum = to_decimal(100)
        self.num_steps.Value = to_decimal(init_steps_clamped)
        self.num_steps.Font = self.font_reg
        self.num_steps.ValueChanged += self._on_num_steps_changed
        self.card_view.Controls.Add(self.num_steps)

        self.lbl_seed = Label()
        self.lbl_seed.Text = u"Seed:"
        self.lbl_seed.Location = Point(14, 366)
        self.lbl_seed.Size = Size(88, 22)
        self.lbl_seed.Font = self.font_small_bold
        self.lbl_seed.ForeColor = self.col_text
        self.card_view.Controls.Add(self.lbl_seed)

        self.trk_seed = TrackBar()
        self.trk_seed.Location = Point(104, 364)
        self.trk_seed.Size = Size(224, 24)
        self.trk_seed.Minimum = 0
        self.trk_seed.Maximum = 1000000
        self.trk_seed.Value = 42
        self.trk_seed.TickStyle = getattr(TickStyle, "None", TickStyle.BottomRight)
        self.trk_seed.AutoSize = False
        self.trk_seed.ValueChanged += self._on_trk_seed_changed
        self.card_view.Controls.Add(self.trk_seed)

        self.num_seed = NumericUpDown()
        self.num_seed.Location = Point(334, 364)
        self.num_seed.Size = Size(86, 24)
        self.num_seed.Minimum = to_decimal(0)
        self.num_seed.Maximum = to_decimal(2147483647)
        self.num_seed.Value = to_decimal(42)
        self.num_seed.Font = self.font_reg
        self.num_seed.ValueChanged += self._on_num_seed_changed
        self.card_view.Controls.Add(self.num_seed)

        # Подсказки при наведении и клике для Edit Guidance, Steps и Seed
        self._bind_param_help(
            self.lbl_cfg,
            [self.trk_guidance, self.num_guidance],
            (
                u"Edit Guidance (Сила следования промпту / CFG Scale)\n"
                u"Определяет, насколько строго нейросеть следует текстовому описанию\n"
                u"› 1.0 — быстрый естественный режим для Qwen-Image-Edit-2511 и z-image-turbo\n"
                u"› 2.5–4.5 — усиленное влияние промпта и негативного промпта\n"
                u"› 7.0+ — жёсткое следование тексту (может перенасыщать детали)"
            ),
        )
        self._bind_param_help(
            self.lbl_st,
            [self.trk_steps, self.num_steps],
            (
                u"Steps (Количество шагов прорисовки)\n"
                u"Число итераций очистки изображения от шума при генерации\n"
                u"› 4 шага — оптимальная скорость для Qwen-Image-Edit-2511 и z-image-turbo\n"
                u"› 6–12 шагов — более детальная проработка текстур фасада, листвы и отражений\n"
                u"› 20–30 шагов — стандарт для классических SDXL-моделей (imageclassic)"
            ),
        )
        self._bind_param_help(
            self.lbl_seed,
            [self.trk_seed, self.num_seed],
            (
                u"Seed (Зерно генерации)\n"
                u"Числовой код случайного шума, определяющий конкретный вариант деталей\n"
                u"› Одинаковый Seed при тех же настройках даёт повторяемый результат\n"
                u"› Нажмите Random Seed для поиска нового варианта освещения и деталей"
            ),
        )

        self.btn_rand_seed = self._create_button(
            self.card_view, u"Random Seed", 422, 341, 118, 25, self.col_accent_soft, self.col_accent
        )
        self.btn_rand_seed.Font = self.font_small_bold
        self.btn_rand_seed.Click += self._on_random_seed_click
        self.tooltip.SetToolTip(
            self.btn_rand_seed,
            u"Сгенерировать новое случайное значение Seed для получения другого варианта деталей и освещения",
        )

        # --- РЯД ПАПКИ СОХРАНЕНИЯ (VAULT) И КНОПКИ START ---
        self.lbl_dir = Label()
        self.lbl_dir.Text = u"Vault:"
        self.lbl_dir.Location = Point(14, 376)
        self.lbl_dir.Size = Size(54, 22)
        self.lbl_dir.Font = Font("Segoe UI", 9.0, FontStyle.Bold | FontStyle.Underline)
        self.lbl_dir.ForeColor = self.col_accent
        self.lbl_dir.Cursor = Cursors.Hand
        self.tooltip.SetToolTip(
            self.lbl_dir,
            u"Нажмите на Vault:, чтобы открыть папку с готовыми рендерами в Проводнике Windows",
        )
        self.lbl_dir.MouseEnter += lambda s, a: setattr(
            self.lbl_dir, "ForeColor", Color.FromArgb(147, 197, 253) if self.is_dark_mode else Color.FromArgb(29, 78, 216)
        )
        self.lbl_dir.MouseLeave += lambda s, a: setattr(
            self.lbl_dir, "ForeColor", self.col_accent
        )
        self.lbl_dir.Click += self._on_open_vault_dir
        self.card_view.Controls.Add(self.lbl_dir)

        self.txt_out_dir = TextBox()
        self.txt_out_dir.Location = Point(72, 374)
        self.txt_out_dir.Size = Size(394, 24)
        self.txt_out_dir.Font = self.font_small
        self.txt_out_dir.Text = u_str(init_out_dir)
        self.tooltip.SetToolTip(
            self.txt_out_dir,
            u"Папка сохранения готовых рендеров (нажмите на Vault: слева для быстрого открытия)",
        )
        self.card_view.Controls.Add(self.txt_out_dir)

        self.btn_browse_dir = self._create_button(
            self.card_view, u"Browse...", 471, 373, 75, 25, self.col_card, self.col_muted
        )
        self.btn_browse_dir.Font = self.font_small
        self.btn_browse_dir.Click += self._on_browse_out_dir

        self.btn_generate = self._create_button(
            self.card_view,
            u"START",
            14,
            408,
            532,
            44,
            self.col_emerald,
            Color.White,
            bold=True,
        )
        self.btn_generate.FlatAppearance.BorderColor = self.col_emerald_dark
        self.btn_generate.Font = Font("Segoe UI", 11.5, FontStyle.Bold)
        self.btn_generate.Click += self._on_generate_click

        # ======================================================================
        # КАРТОЧКА 4 (СПРАВА В СЕРЕДИНЕ): 4 ПРЕВЬЮ (СЕТКА 2x2: КАДРЫ 1..3 + РЕЗУЛЬТАТ)
        # ======================================================================
        self.card_prev = self._create_card(610, 272, 636, 470)

        self.lbl_sec4 = Label()
        self.lbl_sec4.Text = u"IV. PREVIEW & RESULTS"
        self.lbl_sec4.Location = Point(14, 10)
        self.lbl_sec4.Size = Size(320, 20)
        self.lbl_sec4.Font = self.font_sec
        self.lbl_sec4.ForeColor = self.col_dark
        try:
            self.lbl_sec4.UseMnemonic = False
        except Exception:
            pass
        self.card_prev.Controls.Add(self.lbl_sec4)

        self.btn_open_compare = self._create_button(
            self.card_prev, u"Before / After", 506, 7, 114, 25, self.col_card, self.col_muted, role=u"surface"
        )
        self.btn_open_compare.Font = self.font_small_bold
        self.btn_open_compare.Enabled = False
        self.btn_open_compare.Click += self._on_open_compare_click
        self.tooltip.SetToolTip(
            self.btn_open_compare,
            u"Открыть интерактивное окно сравнения исходного кадра и AI-рендера со шторкой Before / After",
        )

        slot_chk_titles = [
            u"1. Scene #1 (Primary)",
            u"2. Scene #2 (Optional)",
            u"3. Scene #3 (Optional)",
        ]
        slot_placeholder_texts = [
            u"Inactive\nSelect a view in Scene #1 or click File...",
            u"Inactive\nSelect a view in Scene #2 or click File...",
            u"Inactive\nSelect a view in Scene #3 or click File...",
        ]

        for s_idx in range(3):
            chk = CheckBox()
            chk.Text = slot_chk_titles[s_idx]
            chk.Font = self.font_small_bold
            chk.ForeColor = self.col_muted
            chk.Checked = False
            chk.CheckedChanged += self._make_slot_chk_handler(s_idx)
            self.card_prev.Controls.Add(chk)
            self.slot_checkboxes.append(chk)

            pic = PictureBox()
            pic.SizeMode = PictureBoxSizeMode.Zoom
            pic.BackColor = self.col_slot_inactive
            pic.BorderStyle = BorderStyle.FixedSingle
            pic.Cursor = Cursors.Hand
            pic.Click += self._make_slot_pic_click_handler(s_idx)
            self.tooltip.SetToolTip(
                pic,
                u"Превью Scene #{}: нажмите для увеличения или создания превью выбранного вида".format(s_idx + 1),
            )
            self.card_prev.Controls.Add(pic)
            self.slot_pic_boxes.append(pic)

            ph = Label()
            ph.Text = slot_placeholder_texts[s_idx]
            ph.Font = self.font_small
            ph.ForeColor = self.col_muted
            ph.BackColor = Color.Transparent
            ph.TextAlign = ContentAlignment.MiddleCenter
            ph.Cursor = Cursors.Hand
            ph.Visible = True
            ph.Click += self._make_slot_placeholder_click_handler(s_idx)
            pic.Controls.Add(ph)
            self.slot_placeholders.append(ph)

        # --- СЛОТ 4: Результат AI-рендера ---
        self.lbl_prev_right = Label()
        self.lbl_prev_right.Text = u"4. AI Render Result (click to enlarge)"
        self.lbl_prev_right.Font = self.font_small_bold
        self.lbl_prev_right.ForeColor = self.col_emerald_dark
        self.card_prev.Controls.Add(self.lbl_prev_right)

        self.pic_result = PictureBox()
        self.pic_result.SizeMode = PictureBoxSizeMode.Zoom
        self.pic_result.BackColor = self.col_slot_active
        self.pic_result.BorderStyle = BorderStyle.FixedSingle
        self.pic_result.Cursor = Cursors.Hand
        self.pic_result.Click += self._on_result_preview_click
        self.tooltip.SetToolTip(self.pic_result, u"Нажмите, чтобы открыть готовый AI-рендер в полном размере")
        self.card_prev.Controls.Add(self.pic_result)

        self.lbl_preview_meta = Label()
        self.lbl_preview_meta.Text = u"Assign any Revit view or external image file to Scene #1..#3"
        self.lbl_preview_meta.Font = self.font_small
        self.lbl_preview_meta.ForeColor = self.col_muted
        self.card_prev.Controls.Add(self.lbl_preview_meta)

        # ======================================================================
        # КАРТОЧКА 5 (ВНИЗУ): ПРОЦЕСС РАБОТЫ, ПРОГРЕСС-БАР И ЖУРНАЛ СОБЫТИЙ
        # ======================================================================
        self.card_prog = self._create_card(16, 752, 1230, 100)

        self.lbl_stage = Label()
        self.lbl_stage.Text = u"Ready — select a view or prompt and press START"
        self.lbl_stage.Location = Point(14, 8)
        self.lbl_stage.Size = Size(1200, 20)
        self.lbl_stage.Font = self.font_sec
        self.lbl_stage.ForeColor = self.col_dark
        self.card_prog.Controls.Add(self.lbl_stage)

        self.progress_bar = ProgressBar()
        self.progress_bar.Location = Point(14, 30)
        self.progress_bar.Size = Size(1200, 12)
        self.progress_bar.Minimum = 0
        self.progress_bar.Maximum = 100
        self.progress_bar.Value = 0
        self.progress_bar.Style = ProgressBarStyle.Continuous
        self.card_prog.Controls.Add(self.progress_bar)

        self.txt_log = TextBox()
        self.txt_log.Location = Point(14, 46)
        self.txt_log.Size = Size(1200, 46)
        self.txt_log.Multiline = True
        self.txt_log.ReadOnly = True
        self.txt_log.ScrollBars = ScrollBars.Vertical
        self.txt_log.BackColor = Color.FromArgb(248, 250, 252)
        self.txt_log.ForeColor = self.col_text
        self.txt_log.Font = self.font_mono
        self.card_prog.Controls.Add(self.txt_log)

        # ======================================================================
        # КНОПКА ВЫХОДА ВНИЗУ СПРАВА ПОД ВСЕМИ БЛОКАМИ: "EXIT | ВЫХОД" + ССЫЛКА GITHUB
        # ======================================================================
        self.lbl_bottom_hint = Label()
        self.lbl_bottom_hint.Text = u"Created by Alexander Iskra"
        self.lbl_bottom_hint.Location = Point(20, 864)
        self.lbl_bottom_hint.AutoSize = True
        self.lbl_bottom_hint.Font = self.font_small
        self.lbl_bottom_hint.ForeColor = self.col_muted
        self.Controls.Add(self.lbl_bottom_hint)

        self.lbl_github_link = Label()
        self.lbl_github_link.Text = u"[github.com/alxiskra/ChutesAI.RevitRender]"
        self.lbl_github_link.Location = Point(170, 864)
        self.lbl_github_link.AutoSize = True
        self.lbl_github_link.Font = Font("Segoe UI", 8.25, FontStyle.Underline)
        self.lbl_github_link.ForeColor = self.col_accent
        self.lbl_github_link.Cursor = Cursors.Hand
        self.tooltip.SetToolTip(self.lbl_github_link, u"Открыть страницу проекта https://github.com/alxiskra/ChutesAI.RevitRender в браузере")
        self.lbl_github_link.MouseEnter += lambda s, a: setattr(
            self.lbl_github_link, "ForeColor", Color.FromArgb(147, 197, 253) if self.is_dark_mode else Color.FromArgb(29, 78, 216)
        )
        self.lbl_github_link.MouseLeave += lambda s, a: setattr(
            self.lbl_github_link, "ForeColor", self.col_accent
        )
        self.lbl_github_link.Click += lambda s, a: open_url_in_browser(u"https://github.com/alxiskra/ChutesAI.RevitRender")
        self.Controls.Add(self.lbl_github_link)

        self.btn_exit_bottom = self._create_button(
            self,
            u"EXIT",
            1066,
            858,
            180,
            34,
            self.col_dark,
            Color.White,
            bold=True,
        )
        self.btn_exit_bottom.Click += lambda s, a: self.Close()

        self.Resize += self._on_form_resize
        self.FormClosed += self._on_form_closed

        # --- ВКЛЮЧЕНИЕ БУФЕРА ОБМЕНА (CTRL+V / CTRL+C / CTRL+X / CTRL+A / CTRL+Z / ПКМ) ВО ВСЕХ ПОЛЯХ ---
        self._all_textboxes = [
            self.txt_base_url,
            self.txt_api_key,
            self.txt_custom_model,
            self.txt_endpoint,
            self.txt_view_search,
            self.txt_prompt,
            self.txt_neg_prompt,
            self.txt_out_dir,
            self.txt_log,
        ]
        for tb_ctrl in self._all_textboxes:
            enable_textbox_clipboard(tb_ctrl)

        self._all_numboxes = [
            self.num_size,
            self.num_width,
            self.num_guidance,
            self.num_steps,
            self.num_seed,
        ]
        for nb_ctrl in self._all_numboxes:
            enable_numeric_clipboard(nb_ctrl)

        self._all_combos = [self.cmb_profile] + list(self.slot_combos)

        # Таймер опроса физических клавиш (GetAsyncKeyState) для обхода перехвата Ctrl+C / Ctrl+V главным окном Revit
        self._kb_prev_state = {}
        self._kbd_timer = Timer()
        self._kbd_timer.Interval = 25
        self._kbd_timer.Tick += self._on_kbd_shortcut_timer_tick
        self._kbd_timer.Start()

        # --- ИНИЦИАЛИЗАЦИЯ ДАННЫХ (БЕЗ АВТОПЕЧАТИ ВИДА И БЕЗ СЕТЕВЫХ ЗАДЕРЖЕК) ---
        try:
            self.MouseDown += self._hide_active_param_help
            for card_pnl in (self.card_conn, self.card_models, self.card_view, self.card_prev, self.card_prog):
                card_pnl.MouseDown += self._hide_active_param_help
                for sub_ctrl in card_pnl.Controls:
                    if sub_ctrl not in (
                        self.lbl_cfg,
                        self.lbl_st,
                        self.lbl_seed,
                        self.lbl_sz,
                        self.lbl_width,
                        self.lbl_custom_m,
                        self.lbl_ep,
                    ):
                        sub_ctrl.MouseDown += self._hide_active_param_help
        except Exception:
            pass
        self._init_profiles_and_inputs(init_api_key, init_base_url)
        self._update_sys_prompt_btn_appearance()
        self._init_all_slots(init_slot1_in, init_slot2_in, init_slot3_in)
        self._refresh_models_list(auto_startup=True)
        self._apply_theme()
        self._apply_responsive_layout()

    # --------------------------------------------------------------------------
    # АДАПТИВНАЯ ВЕРСТКА ПРИ РАСТЯГИВАНИИ / УМЕНЬШЕНИИ ОКНА
    # --------------------------------------------------------------------------
    def _on_form_resize(self, sender, args):
        try:
            self._apply_responsive_layout()
        except Exception:
            pass

    def _apply_responsive_layout(self):
        cw = self.ClientSize.Width
        ch = self.ClientSize.Height
        if cw < 400 or ch < 400:
            return

        margin = 16
        gap = 14
        header_h = 48
        top_row_h = 202
        prog_h = 98
        footer_h = 44

        self.pnl_header.Size = Size(cw, header_h)
        self.btn_theme_toggle.Location = Point(cw - margin - 110, 11)
        self.btn_theme_toggle.Size = Size(110, 26)
        self.lbl_app_sub.Location = Point(max(420, self.btn_theme_toggle.Location.X - 310), 14)
        self.lbl_app_sub.Size = Size(300, 20)

        total_w = cw - margin * 2
        left_w = max(510, int(total_w * 0.47))
        right_w = max(490, total_w - left_w - gap)
        right_x = margin + left_w + gap

        mid_y = header_h + 10 + top_row_h + 10
        mid_h = max(445, ch - mid_y - prog_h - footer_h - 18)

        # Карточка 1
        self.card_conn.Location = Point(margin, header_h + 10)
        self.card_conn.Size = Size(left_w, top_row_h)
        inner_l = left_w - 28
        self.btn_del_prof.Location = Point(left_w - 14 - 78, 34)
        self.btn_save_prof.Location = Point(self.btn_del_prof.Location.X - 6 - 94, 34)
        self.cmb_profile.Size = Size(max(140, self.btn_save_prof.Location.X - 96), 24)
        try:
            self.cmb_profile.SelectionLength = 0
            self.cmb_profile.Invalidate()
        except Exception:
            pass
        self.txt_base_url.Size = Size(max(200, left_w - 104), 24)
        self.btn_toggle_key.Location = Point(left_w - 14 - 74, 103)
        self.txt_api_key.Size = Size(max(180, self.btn_toggle_key.Location.X - 96), 24)
        self.btn_fetch_models.Size = Size(inner_l, 34)
        self.lbl_prof_path.Size = Size(inner_l, 16)

        # Карточка 2
        self.card_models.Location = Point(right_x, header_h + 10)
        self.card_models.Size = Size(right_w, top_row_h)
        inner_r = right_w - 28
        self.lbl_sec2.Size = Size(max(240, right_w - 230), 20)
        self.lbl_models_status.Location = Point(max(260, right_w - 224), 9)
        self.lbl_models_status.Size = Size(210, 18)
        self.lst_models.Size = Size(inner_r, 82)

        self.btn_del_model.Location = Point(right_w - 14 - 80, 114)
        self.btn_del_model.Size = Size(80, 24)
        self.btn_add_model.Location = Point(self.btn_del_model.Location.X - 6 - 100, 114)
        self.btn_add_model.Size = Size(100, 24)
        self.txt_custom_model.Location = Point(98, 115)
        self.txt_custom_model.Size = Size(max(120, self.btn_add_model.Location.X - 104), 22)

        self.txt_endpoint.Location = Point(98, 143)
        self.txt_endpoint.Size = Size(max(200, right_w - 112), 22)
        half_chk_w = max(200, int(inner_r * 0.50))
        self.chk_send_image.Location = Point(14, 171)
        self.chk_send_image.Size = Size(half_chk_w, 22)
        self.chk_retry_busy.Location = Point(14 + half_chk_w + 6, 171)
        self.chk_retry_busy.Size = Size(max(180, inner_r - half_chk_w - 6), 22)

        # Карточка 3
        self.card_view.Location = Point(margin, mid_y)
        self.card_view.Size = Size(left_w, mid_h)
        self.lbl_sec3.Size = Size(inner_l, 20)

        # Ширина блока [File... (58px)] + 4px + [✕ (26px)] = 88px — строго равна ширине обеих кнопок [+Template (88px)],
        # поэтому левый край «File...» и левый край правой «+Template» стоят идеально заподлицо!
        file_btn_w = 58
        clear_btn_w = 26
        tpl_btn_w = file_btn_w + 4 + clear_btn_w  # 88 px
        file_col_x = (left_w - 14 - clear_btn_w) - 4 - file_btn_w
        cmb_w = max(160, file_col_x - 94 - 6)

        # Блок [txt_view_search + btn_clear_search] начинается на X=94 и заканчивается строго заподлицо с нижними списками Scene #1..#3 (94 + cmb_w),
        # а чекбокс «2D View» располагается ровно над кнопкой «File...» (X = file_col_x)
        clear_search_w = 56
        self.btn_clear_search.Location = Point(94 + cmb_w - clear_search_w, 31)
        self.btn_clear_search.Size = Size(clear_search_w, 25)
        self.txt_view_search.Location = Point(94, 32)
        self.txt_view_search.Size = Size(max(100, self.btn_clear_search.Location.X - 94 - 4), 24)
        self.chk_all_views.Location = Point(file_col_x, 34)
        self.chk_all_views.Size = Size(tpl_btn_w, 20)

        for s_idx in range(3):
            row_y = 62 + s_idx * 28
            self.slot_clear_btns[s_idx].Location = Point(left_w - 14 - clear_btn_w, row_y - 1)
            self.slot_clear_btns[s_idx].Size = Size(clear_btn_w, 25)
            self.slot_file_btns[s_idx].Location = Point(file_col_x, row_y - 1)
            self.slot_file_btns[s_idx].Size = Size(file_btn_w, 25)
            self.slot_combos[s_idx].Location = Point(94, row_y)
            self.slot_combos[s_idx].Size = Size(cmb_w, 24)

        btn_start_y = mid_h - 48
        dir_row_y = btn_start_y - 30
        seed_row_y = dir_row_y - 28
        steps_row_y = seed_row_y - 28
        cfg_row_y = steps_row_y - 28
        size_row_y = cfg_row_y - 29

        prompt_hdr_y = 148
        prompt_top_y = 173
        prompt_h = max(54, size_row_y - prompt_top_y - 7)
        col_pr_gap = 10
        half_pr_w = max(180, int((inner_l - col_pr_gap) // 2))
        right_pr_x = 14 + half_pr_w + col_pr_gap
        right_pr_w = max(180, (left_w - 14) - right_pr_x)

        self.lbl_pr.Location = Point(14, prompt_hdr_y + 2)
        self.lbl_pr.Size = Size(56, 20)
        self.btn_pos_tpl.Location = Point(14 + half_pr_w - tpl_btn_w, prompt_hdr_y - 3)
        self.btn_pos_tpl.Size = Size(tpl_btn_w, 25)
        sys_btn_x = 72
        sys_btn_w = max(88, self.btn_pos_tpl.Location.X - 6 - sys_btn_x)
        self.btn_sys_prompt.Location = Point(sys_btn_x, prompt_hdr_y - 3)
        self.btn_sys_prompt.Size = Size(sys_btn_w, 25)

        self.btn_neg_tpl.Location = Point(left_w - 14 - tpl_btn_w, prompt_hdr_y - 3)
        self.btn_neg_tpl.Size = Size(tpl_btn_w, 25)
        self.lbl_neg_pr.Location = Point(right_pr_x, prompt_hdr_y + 2)
        self.lbl_neg_pr.Size = Size(max(115, self.btn_neg_tpl.Location.X - right_pr_x - 4), 20)

        self.txt_prompt.Location = Point(14, prompt_top_y)
        self.txt_prompt.Size = Size(half_pr_w, prompt_h)
        self.txt_neg_prompt.Location = Point(right_pr_x, prompt_top_y)
        self.txt_neg_prompt.Size = Size(right_pr_w, prompt_h)

        # 3 ряда ползунков строго друг под другом (одинаковая координата X и одинаковая ширина ползунков и полей ввода)
        slider_x = 104
        rand_btn_w = 118
        rand_btn_x = left_w - 14 - rand_btn_w
        num_box_w = 88
        num_box_x = rand_btn_x - 6 - num_box_w
        slider_w = max(80, num_box_x - slider_x - 6)

        # Ряд размеров: Height -> Width -> Кнопка Auto Width (после Height и Width, размером точно как Random Seed)
        self.lbl_sz.Location = Point(14, size_row_y + 3)
        self.lbl_sz.Size = Size(54, 22)
        self.num_size.Location = Point(70, size_row_y)
        self.num_size.Size = Size(76, 24)

        self.lbl_width.Location = Point(156, size_row_y + 3)
        self.lbl_width.Size = Size(48, 22)
        self.num_width.Location = Point(206, size_row_y)
        self.num_width.Size = Size(76, 24)

        # Кнопка Auto Width заканчивается строго заподлицо с правым краем счётчиков NumericUpDown (num_box_x + num_box_w)
        auto_w_btn_x = 292
        auto_w_btn_w = max(118, (num_box_x + num_box_w) - auto_w_btn_x)
        self.btn_toggle_width.Location = Point(auto_w_btn_x, size_row_y - 1)
        self.btn_toggle_width.Size = Size(auto_w_btn_w, 25)

        self.lbl_cfg.Location = Point(14, cfg_row_y + 3)
        self.lbl_cfg.Size = Size(88, 22)
        self.trk_guidance.Location = Point(slider_x, cfg_row_y)
        self.trk_guidance.Size = Size(slider_w, 24)
        self.num_guidance.Location = Point(num_box_x, cfg_row_y)
        self.num_guidance.Size = Size(num_box_w, 24)

        self.lbl_st.Location = Point(14, steps_row_y + 3)
        self.lbl_st.Size = Size(88, 22)
        self.trk_steps.Location = Point(slider_x, steps_row_y)
        self.trk_steps.Size = Size(slider_w, 24)
        self.num_steps.Location = Point(num_box_x, steps_row_y)
        self.num_steps.Size = Size(num_box_w, 24)

        self.lbl_seed.Location = Point(14, seed_row_y + 3)
        self.lbl_seed.Size = Size(88, 22)
        self.trk_seed.Location = Point(slider_x, seed_row_y)
        self.trk_seed.Size = Size(slider_w, 24)
        self.num_seed.Location = Point(num_box_x, seed_row_y)
        self.num_seed.Size = Size(num_box_w, 24)
        self.btn_rand_seed.Location = Point(rand_btn_x, seed_row_y - 1)
        self.btn_rand_seed.Size = Size(rand_btn_w, 25)

        self.lbl_dir.Location = Point(14, dir_row_y + 3)
        self.lbl_dir.Size = Size(54, 22)
        self.btn_browse_dir.Location = Point(left_w - 14 - 75, dir_row_y - 1)
        self.txt_out_dir.Location = Point(72, dir_row_y)
        self.txt_out_dir.Size = Size(max(150, self.btn_browse_dir.Location.X - 78), 24)

        self.btn_generate.Location = Point(14, btn_start_y)
        self.btn_generate.Size = Size(inner_l, 42)

        # Карточка 4 (справа — сетка 2x2 из 4 превью)
        self.card_prev.Location = Point(right_x, mid_y)
        self.card_prev.Size = Size(right_w, mid_h)
        cmp_btn_w = 114
        self.btn_open_compare.Location = Point(right_w - 14 - cmp_btn_w, 6)
        self.btn_open_compare.Size = Size(cmp_btn_w, 25)
        self.lbl_sec4.Size = Size(max(180, self.btn_open_compare.Location.X - 24), 20)
        try:
            self.btn_open_compare.BringToFront()
        except Exception:
            pass

        col_gap = 14
        cell_w = max(180, int((inner_r - col_gap) / 2))
        avail_h = max(210, mid_h - 34 - 42)
        row_block_h = int((avail_h - 8) / 2)
        pic_h = max(90, row_block_h - 22)

        col1_x = 14
        col2_x = 14 + cell_w + col_gap
        row1_hdr_y = 34
        row1_pic_y = row1_hdr_y + 21
        row2_hdr_y = row1_pic_y + pic_h + 8
        row2_pic_y = row2_hdr_y + 21

        self.slot_checkboxes[0].Location = Point(col1_x, row1_hdr_y)
        self.slot_checkboxes[0].Size = Size(cell_w, 20)
        self.slot_pic_boxes[0].Location = Point(col1_x, row1_pic_y)
        self.slot_pic_boxes[0].Size = Size(cell_w, pic_h)
        self.slot_placeholders[0].Location = Point(4, 4)
        self.slot_placeholders[0].Size = Size(max(60, cell_w - 8), max(40, pic_h - 8))

        self.slot_checkboxes[1].Location = Point(col2_x, row1_hdr_y)
        self.slot_checkboxes[1].Size = Size(cell_w, 20)
        self.slot_pic_boxes[1].Location = Point(col2_x, row1_pic_y)
        self.slot_pic_boxes[1].Size = Size(cell_w, pic_h)
        self.slot_placeholders[1].Location = Point(4, 4)
        self.slot_placeholders[1].Size = Size(max(60, cell_w - 8), max(40, pic_h - 8))

        self.slot_checkboxes[2].Location = Point(col1_x, row2_hdr_y)
        self.slot_checkboxes[2].Size = Size(cell_w, 20)
        self.slot_pic_boxes[2].Location = Point(col1_x, row2_pic_y)
        self.slot_pic_boxes[2].Size = Size(cell_w, pic_h)
        self.slot_placeholders[2].Location = Point(4, 4)
        self.slot_placeholders[2].Size = Size(max(60, cell_w - 8), max(40, pic_h - 8))

        self.lbl_prev_right.Location = Point(col2_x, row2_hdr_y + 1)
        self.lbl_prev_right.Size = Size(cell_w, 18)
        self.pic_result.Location = Point(col2_x, row2_pic_y)
        self.pic_result.Size = Size(cell_w, pic_h)

        self.lbl_preview_meta.Location = Point(14, row2_pic_y + pic_h + 5)
        self.lbl_preview_meta.Size = Size(inner_r, 32)

        # Карточка 5
        prog_y = mid_y + mid_h + 8
        self.card_prog.Location = Point(margin, prog_y)
        self.card_prog.Size = Size(total_w, prog_h)
        self.lbl_stage.Size = Size(total_w - 28, 20)
        self.progress_bar.Size = Size(total_w - 28, 12)
        self.txt_log.Size = Size(total_w - 28, 44)

        exit_y = prog_y + prog_h + 6
        self.lbl_bottom_hint.Location = Point(margin + 2, exit_y + 8)
        self.lbl_github_link.Location = Point(self.lbl_bottom_hint.Right + 4, exit_y + 8)
        self.btn_exit_bottom.Location = Point(cw - margin - 180, exit_y)
        self.btn_exit_bottom.Size = Size(180, 34)

    def _on_kbd_shortcut_timer_tick(self, sender, args):
        """
        Обходит перехват горячих клавиш (Ctrl+C, Ctrl+V, Ctrl+X, Ctrl+A, Ctrl+Z) циклом сообщений Revit
        (PreTranslateMessage / TranslateAccelerator) для немодального окна form.Show().
        """
        try:
            focused_tb = None
            for tb in self._all_textboxes:
                if tb is not None and tb.Focused:
                    focused_tb = tb
                    break
            focused_nb = None
            if focused_tb is None:
                for nb in getattr(self, "_all_numboxes", ()):
                    if nb is not None and (nb.Focused or nb.ContainsFocus):
                        focused_nb = nb
                        break
            if focused_tb is None and focused_nb is None:
                self._kb_prev_state.clear()
                return

            u32 = ctypes.windll.user32
            ctrl_down = (u32.GetAsyncKeyState(0x11) & 0x8000) != 0
            shift_down = (u32.GetAsyncKeyState(0x10) & 0x8000) != 0
            alt_down = (u32.GetAsyncKeyState(0x12) & 0x8000) != 0

            if alt_down or (not ctrl_down and not shift_down):
                self._kb_prev_state.clear()
                return

            now_ts = time.time()

            def _edge_pressed(vk_code):
                is_dn = (u32.GetAsyncKeyState(vk_code) & 0x8000) != 0
                was_dn = self._kb_prev_state.get(vk_code, False)
                self._kb_prev_state[vk_code] = is_dn
                return is_dn and (not was_dn)

            if focused_nb is not None:
                if ctrl_down and not shift_down:
                    if _edge_pressed(0x56):
                        if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                            _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                            paste_into_numeric_updown(focused_nb)
                    elif _edge_pressed(0x43) or _edge_pressed(0x2D):
                        if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                            _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                            copy_from_numeric_updown(focused_nb)
                elif shift_down and not ctrl_down:
                    if _edge_pressed(0x2D):
                        if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                            _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                            paste_into_numeric_updown(focused_nb)
                return

            if ctrl_down and not shift_down:
                # V (0x56), C (0x43), X (0x58), A (0x41), Z (0x5A), Insert (0x2D)
                if _edge_pressed(0x56):
                    if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                        _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                        paste_into_textbox(focused_tb)
                elif _edge_pressed(0x43) or _edge_pressed(0x2D):
                    if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                        _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                        copy_from_textbox(focused_tb, copy_all_if_unselected=False)
                elif _edge_pressed(0x58):
                    if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                        _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                        cut_from_textbox(focused_tb)
                elif _edge_pressed(0x41):
                    if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                        _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                        focused_tb.SelectAll()
                elif _edge_pressed(0x5A):
                    if not focused_tb.ReadOnly and (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                        _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                        focused_tb.Undo()
            elif shift_down and not ctrl_down:
                # Shift+Insert (0x2D) -> Paste, Shift+Delete (0x2E) -> Cut
                if _edge_pressed(0x2D):
                    if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                        _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                        paste_into_textbox(focused_tb)
                elif _edge_pressed(0x2E):
                    if (now_ts - _LAST_CLIPBOARD_SHORTCUT_TS[0]) > 0.15:
                        _LAST_CLIPBOARD_SHORTCUT_TS[0] = now_ts
                        cut_from_textbox(focused_tb)
        except Exception:
            pass

    def _on_form_closed(self, sender, args):
        try:
            if hasattr(self, "_param_hover_timer") and self._param_hover_timer is not None:
                self._param_hover_timer.Stop()
                self._param_hover_timer.Dispose()
        except Exception:
            pass
        try:
            if hasattr(self, "_kbd_timer") and self._kbd_timer is not None:
                self._kbd_timer.Stop()
                self._kbd_timer.Dispose()
        except Exception:
            pass
        for pic_box in list(self.slot_pic_boxes) + [self.pic_result]:
            try:
                if pic_box.Image is not None:
                    pic_box.Image.Dispose()
            except Exception:
                pass
        try:
            AppDomain.CurrentDomain.SetData("DynamoChutesAI_ActiveForm", None)
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # ОБРАБОТЧИКИ ПОЛЗУНКОВ, СИДА, РАЗМЕРОВ, СИСТЕМНОГО ПРОМПТА И ШАБЛОНОВ
    # --------------------------------------------------------------------------
    def _on_combo_draw_item(self, sender, e):
        """Отрисовывает выпадающие списки ComboBox (Scene #1..#3) в тёмной теме."""
        try:
            try:
                st_val = Convert.ToInt32(e.State)
                sel_bit = Convert.ToInt32(DrawItemState.Selected)
                edit_bit = Convert.ToInt32(DrawItemState.ComboBoxEdit)
                is_sel = ((st_val & sel_bit) != 0) and ((st_val & edit_bit) == 0)
            except Exception:
                is_sel = False
            bg = self.col_accent_soft if is_sel else self.col_input_bg
            fg = self.col_accent if is_sel else self.col_text
            br_bg = SolidBrush(bg)
            e.Graphics.FillRectangle(br_bg, e.Bounds)
            br_bg.Dispose()
            idx = int(e.Index)
            if 0 <= idx < sender.Items.Count:
                txt = u_str(sender.Items[idx])
                try:
                    t_rect = Rectangle(
                        int(e.Bounds.X + 3),
                        int(e.Bounds.Y),
                        max(10, int(e.Bounds.Width - 6)),
                        int(e.Bounds.Height),
                    )
                    t_flags = (
                        TextFormatFlags.VerticalCenter
                        | TextFormatFlags.Left
                        | TextFormatFlags.SingleLine
                        | TextFormatFlags.NoPrefix
                        | TextFormatFlags.PreserveGraphicsClipping
                    )
                    TextRenderer.DrawText(e.Graphics, txt, sender.Font, t_rect, fg, bg, t_flags)
                except Exception:
                    try:
                        e.Graphics.TextRenderingHint = TextRenderingHint.ClearTypeGridFit
                    except Exception:
                        pass
                    ty = int(e.Bounds.Y) + max(0, int((e.Bounds.Height - sender.Font.Height) // 2))
                    br_fg = SolidBrush(fg)
                    e.Graphics.DrawString(txt, sender.Font, br_fg, float(e.Bounds.X + 4), float(ty))
                    br_fg.Dispose()
        except Exception:
            pass

    def _on_toggle_theme(self, sender, args):
        self.is_dark_mode = not bool(self.is_dark_mode)
        self.profiles_data["ui_dark_mode"] = self.is_dark_mode
        save_profiles_data(self.profiles_data)
        self._apply_theme()

    def _apply_theme(self):
        self._set_palette_colors(self.is_dark_mode)
        self.BackColor = self.col_bg
        self.pnl_header.BackColor = self.col_header_bg
        try:
            self.lbl_app_title.UseCompatibleTextRendering = False
            self.lbl_app_sub.UseCompatibleTextRendering = False
            self.lbl_bottom_hint.UseCompatibleTextRendering = False
            # Подчёркнутые ссылки оставляем на GDI+ (True), чтобы линия подчёркивания не пересекала нижнюю петельку буквы "g"
            self.lbl_github_link.UseCompatibleTextRendering = True
            self.lbl_dir.UseCompatibleTextRendering = True
        except Exception:
            pass
        self.btn_theme_toggle.Text = u"Theme: Dark" if self.is_dark_mode else u"Theme: Light"
        self._style_button_by_role(self.btn_theme_toggle)

        cards = (self.card_conn, self.card_models, self.card_view, self.card_prev, self.card_prog)
        sec_labels = (self.lbl_sec1, self.lbl_sec2, self.lbl_sec3, self.lbl_sec4, self.lbl_stage)
        accent_labels = (self.lbl_models_status, self.lbl_dir, self.lbl_github_link, self.chk_retry_busy)
        text_labels = (
            self.lbl_custom_m, self.lbl_ep, self.chk_send_image,
            self.lbl_pr, self.lbl_sz, self.lbl_width, self.lbl_cfg, self.lbl_st, self.lbl_seed,
        )
        for card in cards:
            card.BackColor = self.col_card
            for ctrl in card.Controls:
                if isinstance(ctrl, Button):
                    self._style_button_by_role(ctrl)
                elif isinstance(ctrl, (TextBox, ComboBox, ListBox, NumericUpDown)):
                    ctrl.BackColor = self.col_log_bg if ctrl is self.txt_log else self.col_input_bg
                    if ctrl is self.txt_prompt:
                        ctrl.ForeColor = self.col_prompt_fg
                        ctrl.Font = self.font_prompt
                    elif ctrl is self.txt_neg_prompt:
                        ctrl.ForeColor = self.col_neg_prompt_fg
                        ctrl.Font = self.font_prompt
                    else:
                        ctrl.ForeColor = self.col_text
                    if isinstance(ctrl, ComboBox):
                        try:
                            ctrl.FlatStyle = FlatStyle.Popup if self.is_dark_mode else FlatStyle.Standard
                            if ctrl in self.slot_combos:
                                ctrl.DrawMode = DrawMode.OwnerDrawFixed if self.is_dark_mode else DrawMode.Normal
                        except Exception:
                            pass
                        ctrl.Invalidate()
                elif isinstance(ctrl, TrackBar):
                    ctrl.BackColor = self.col_card
                elif isinstance(ctrl, (Label, CheckBox)):
                    try:
                        if isinstance(ctrl, Label):
                            ctrl.UseMnemonic = False
                        if ctrl is not self.lbl_dir:
                            ctrl.UseCompatibleTextRendering = False
                    except Exception:
                        pass
                    if ctrl is self.lbl_prev_right:
                        ctrl.ForeColor = self.col_emerald if self.is_dark_mode else self.col_emerald_dark
                    elif ctrl in sec_labels:
                        ctrl.ForeColor = self.col_sec_hdr
                    elif ctrl in accent_labels:
                        ctrl.ForeColor = self.col_accent
                    elif ctrl in text_labels:
                        ctrl.ForeColor = self.col_text
                    else:
                        ctrl.ForeColor = self.col_muted

        self.lbl_bottom_hint.ForeColor = self.col_muted
        self.lbl_github_link.ForeColor = self.col_accent
        self._style_button_by_role(self.btn_exit_bottom)
        self.pic_result.BackColor = self.col_slot_active
        self._update_sys_prompt_btn_appearance()
        self._update_compare_btn_appearance()
        self._sync_width_btn_appearance()
        for s_idx in range(3):
            try:
                self.slot_placeholders[s_idx].UseCompatibleTextRendering = False
            except Exception:
                pass
            self._sync_slot_visual_state(s_idx)

    def _update_sys_prompt_btn_appearance(self):
        is_active = bool(self.profiles_data.get("use_system_prompt", False)) and bool(
            u_str(self.profiles_data.get("system_prompt", u"")).strip()
        )
        if is_active:
            self.btn_sys_prompt.Text = u"Sys.Prompt [on]"
            self.btn_sys_prompt.Tag = u"emerald_soft"
        else:
            self.btn_sys_prompt.Text = u"Sys.Prompt [off]"
            self.btn_sys_prompt.Tag = u"surface"
        self._style_button_by_role(self.btn_sys_prompt)

    def _update_compare_btn_appearance(self):
        has_res = bool(self.btn_open_compare.Enabled) and bool(
            self.result_image_path and File.Exists(self.result_image_path)
        )
        self.btn_open_compare.Tag = u"emerald_soft" if has_res else u"surface"
        self._style_button_by_role(self.btn_open_compare)

    def _on_sys_prompt_click(self, sender, args):
        changed = show_system_prompt_dialog(self, self.profiles_data)
        self._update_sys_prompt_btn_appearance()
        if changed:
            state_str = u"ON" if self.profiles_data.get("use_system_prompt") else u"OFF"
            self.log_step(u"System Prompt updated ({})".format(state_str), progress_val=0)

    def _on_pos_templates_click(self, sender, args):
        show_prompt_templates_dialog(self, self.profiles_data, self.txt_prompt, is_negative=False)

    def _on_neg_templates_click(self, sender, args):
        show_prompt_templates_dialog(self, self.profiles_data, self.txt_neg_prompt, is_negative=True)

    def _on_trk_guidance_changed(self, sender, args):
        if self._syncing_params:
            return
        self._syncing_params = True
        try:
            val = round(float(self.trk_guidance.Value) / 10.0, 1)
            self.num_guidance.Value = to_decimal(val)
        except Exception:
            pass
        self._syncing_params = False

    def _on_num_guidance_changed(self, sender, args):
        if self._syncing_params:
            return
        self._syncing_params = True
        try:
            val_flt = from_decimal_float(self.num_guidance.Value, 1.0)
            val_int = int(round(val_flt * 10.0))
            val_int = max(self.trk_guidance.Minimum, min(self.trk_guidance.Maximum, val_int))
            self.trk_guidance.Value = val_int
        except Exception:
            pass
        self._syncing_params = False

    def _on_trk_steps_changed(self, sender, args):
        if self._syncing_params:
            return
        self._syncing_params = True
        try:
            self.num_steps.Value = to_decimal(int(self.trk_steps.Value))
        except Exception:
            pass
        self._syncing_params = False

    def _on_num_steps_changed(self, sender, args):
        if self._syncing_params:
            return
        self._syncing_params = True
        try:
            v = from_decimal_int(self.num_steps.Value, 4)
            v = max(self.trk_steps.Minimum, min(self.trk_steps.Maximum, v))
            self.trk_steps.Value = v
        except Exception:
            pass
        self._syncing_params = False

    def _on_trk_seed_changed(self, sender, args):
        if self._syncing_params:
            return
        self._syncing_params = True
        try:
            self.num_seed.Value = to_decimal(int(self.trk_seed.Value))
        except Exception:
            pass
        self._syncing_params = False

    def _on_num_seed_changed(self, sender, args):
        if self._syncing_params:
            return
        self._syncing_params = True
        try:
            v = from_decimal_int(self.num_seed.Value, 42)
            self.trk_seed.Value = max(self.trk_seed.Minimum, min(self.trk_seed.Maximum, v))
        except Exception:
            pass
        self._syncing_params = False

    def _on_random_seed_click(self, sender, args):
        rnd = random.randint(1, 999999)
        self._syncing_params = True
        try:
            self.num_seed.Value = to_decimal(rnd)
            self.trk_seed.Value = max(self.trk_seed.Minimum, min(self.trk_seed.Maximum, rnd))
        except Exception:
            pass
        self._syncing_params = False
        self.log_step(u"Random Seed set to {}".format(rnd), progress_val=0)

    def _sync_width_btn_appearance(self):
        if self.manual_width_enabled:
            self.num_width.Enabled = True
            self.btn_toggle_width.Text = u"Manual W×H"
            self.btn_toggle_width.Tag = u"emerald"
        else:
            self.num_width.Enabled = False
            self.btn_toggle_width.Text = u"Auto Width"
            self.btn_toggle_width.Tag = u"accent_soft"
        self._style_button_by_role(self.btn_toggle_width)

    def _on_toggle_manual_width(self, sender, args):
        self.manual_width_enabled = not self.manual_width_enabled
        self._sync_width_btn_appearance()
        if self.manual_width_enabled:
            self.log_step(u"Manual W×H mode enabled (custom width and height in px)", progress_val=0)
        else:
            self._recalc_auto_width_preview()
            self.log_step(u"Auto Width mode enabled (aspect ratio matched to scene)", progress_val=0)

    def _on_height_value_changed(self, sender, args):
        if not self.manual_width_enabled:
            self._recalc_auto_width_preview()

    def _recalc_auto_width_preview(self):
        """Показывает рассчитанную ширину Width при авто-подгоне, если есть превью активного слота."""
        if self.manual_width_enabled:
            return
        ref_path = u""
        for s_idx in range(3):
            slot = self.slots[s_idx]
            p = slot["preview_path"] or slot["file_path"]
            if slot["enabled"] and p and File.Exists(p):
                ref_path = p
                break
        base_val = from_decimal_int(self.num_size.Value, 1024)
        if ref_path:
            calc_w, calc_h = calc_target_dimensions(ref_path, base_val)
            try:
                self.num_width.Value = to_decimal(calc_w)
            except Exception:
                pass
        else:
            try:
                self.num_width.Value = to_decimal(base_val)
            except Exception:
                pass

    # --------------------------------------------------------------------------
    # ЛОГИРОВАНИЕ И ИНФОРМАЦИОННАЯ СТРОКА СЛОТОВ
    # --------------------------------------------------------------------------
    def log_step(self, message, progress_val=0, status_color=None):
        stamp = time.strftime("%H:%M:%S")
        line = u"[{}] {}".format(stamp, u_str(message))
        self.lbl_stage.Text = u_str(message)
        if status_color is not None:
            self.lbl_stage.ForeColor = status_color
        else:
            self.lbl_stage.ForeColor = self.col_sec_hdr
        if progress_val is not None:
            self.progress_bar.Value = max(0, min(100, int(progress_val)))
        prev_text = u_str(self.txt_log.Text)
        if prev_text:
            self.txt_log.Text = prev_text + u"\r\n" + line
        else:
            self.txt_log.Text = line
        try:
            self.txt_log.SelectionStart = len(self.txt_log.Text)
            self.txt_log.ScrollToCaret()
        except Exception:
            pass
        Application.DoEvents()

    def _get_slot_short_description(self, s_idx):
        slot = self.slots[s_idx]
        if slot["source_type"] == "file" and slot["file_path"]:
            return u"File: {}".format(Path.GetFileName(slot["file_path"]))
        if slot["source_type"] == "view" and slot["view_name"]:
            return u"View: {}".format(slot["view_name"])
        return u"Inactive"

    def _update_active_slots_summary(self):
        active_parts = []
        for s_idx in range(3):
            slot = self.slots[s_idx]
            if slot["enabled"] and slot["source_type"] in ("view", "file"):
                active_parts.append(u"#{}: {}".format(s_idx + 1, self._get_slot_short_description(s_idx)))
        if active_parts:
            summary_str = u"  |  ".join(active_parts)
        else:
            summary_str = u"none selected (select a 3D view/file or use Text-to-Image)"
        self.lbl_preview_meta.Text = u"Active scenes ({}/3): {}".format(len(active_parts), summary_str)
        self._recalc_auto_width_preview()

    # --------------------------------------------------------------------------
    # УПРАВЛЕНИЕ ПРОФИЛЯМИ И ПОЛЬЗОВАТЕЛЬСКИМИ МОДЕЛЯМИ
    # --------------------------------------------------------------------------
    def _get_active_profile_dict(self):
        p_name = u_str(self.cmb_profile.Text).strip() or u"Chutes.ai"
        profiles_dict = self.profiles_data.get("profiles", {})
        if p_name not in profiles_dict:
            profiles_dict[p_name] = {
                "base_url": u_str(self.txt_base_url.Text).strip() or u"https://api.chutes.ai",
                "api_key": u_str(self.txt_api_key.Text).strip(),
                "last_model": u"Qwen-Image-Edit-2511",
                "custom_models": [],
            }
        if "custom_models" not in profiles_dict[p_name] or not isinstance(profiles_dict[p_name]["custom_models"], list):
            profiles_dict[p_name]["custom_models"] = []
        return p_name, profiles_dict[p_name]

    def _init_profiles_and_inputs(self, init_api_key, init_base_url):
        self.cmb_profile.Items.Clear()
        profiles_dict = self.profiles_data.get("profiles", {})
        for p_name in sorted(profiles_dict.keys()):
            self.cmb_profile.Items.Add(u_str(p_name))
        active_name = u_str(self.profiles_data.get("active_profile", u""))
        if active_name in profiles_dict:
            self.cmb_profile.Text = active_name
            prof = profiles_dict[active_name]
            self.txt_base_url.Text = u_str(prof.get("base_url", u"https://api.chutes.ai"))
            self.txt_api_key.Text = u_str(prof.get("api_key", u""))
        elif len(profiles_dict) > 0:
            first_key = sorted(profiles_dict.keys())[0]
            self.cmb_profile.Text = u_str(first_key)
            prof = profiles_dict[first_key]
            self.txt_base_url.Text = u_str(prof.get("base_url", u"https://api.chutes.ai"))
            self.txt_api_key.Text = u_str(prof.get("api_key", u""))
        if init_base_url:
            self.txt_base_url.Text = u_str(init_base_url)
        if init_api_key:
            self.txt_api_key.Text = u_str(init_api_key)

    def _on_profile_selected(self, sender, args):
        p_name = u_str(self.cmb_profile.Text).strip()
        profiles_dict = self.profiles_data.get("profiles", {})
        if p_name in profiles_dict:
            prof = profiles_dict[p_name]
            self.txt_base_url.Text = u_str(prof.get("base_url", u"https://api.chutes.ai"))
            self.txt_api_key.Text = u_str(prof.get("api_key", u""))
            self.profiles_data["active_profile"] = p_name
            save_profiles_data(self.profiles_data)
            self._refresh_models_list(auto_startup=True)
            self.log_step(u"Profile '{}' loaded".format(p_name), progress_val=0)

    def _on_save_profile(self, sender, args):
        p_name, prof_obj = self._get_active_profile_dict()
        self.cmb_profile.Text = p_name
        prof_obj["base_url"] = u_str(self.txt_base_url.Text).strip() or u"https://api.chutes.ai"
        prof_obj["api_key"] = u_str(self.txt_api_key.Text).strip()
        prof_obj["last_model"] = u_str(self.selected_model_info.get("id", u"Qwen-Image-Edit-2511"))
        self.profiles_data["active_profile"] = p_name
        if p_name not in [u_str(self.cmb_profile.Items[i]) for i in range(self.cmb_profile.Items.Count)]:
            self.cmb_profile.Items.Add(p_name)
        ok = save_profiles_data(self.profiles_data)
        if ok:
            self.log_step(u"Profile '{}' saved".format(p_name), progress_val=0, status_color=self.col_success)
        else:
            self.log_step(u"Failed to save profile file", progress_val=0)

    def _on_delete_profile(self, sender, args):
        p_name = u_str(self.cmb_profile.Text).strip()
        profiles_dict = self.profiles_data.get("profiles", {})
        if p_name in profiles_dict and len(profiles_dict) > 1:
            del profiles_dict[p_name]
            first_remaining = sorted(profiles_dict.keys())[0]
            self.profiles_data["active_profile"] = first_remaining
            save_profiles_data(self.profiles_data)
            self._init_profiles_and_inputs(None, None)
            self._refresh_models_list(auto_startup=True)
            self.log_step(u"Profile '{}' deleted".format(p_name), progress_val=0)
        else:
            self.log_step(u"Cannot delete the only remaining profile", progress_val=0)

    def _on_toggle_api_key(self, sender, args):
        self.txt_api_key.UseSystemPasswordChar = not self.txt_api_key.UseSystemPasswordChar
        self.btn_toggle_key.Text = u"Show" if self.txt_api_key.UseSystemPasswordChar else u"Hide"

    def _on_add_custom_model_click(self, sender, args):
        raw_m = u_str(self.txt_custom_model.Text).strip()
        if not raw_m:
            MessageBox.Show(
                u"Enter a model name or ID in Add Model (and optionally an Endpoint below), then click + To Profile",
                u"Add Custom Model",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information,
            )
            return

        base_url = u_str(self.txt_base_url.Text).strip() or u"https://api.chutes.ai"
        curr_ep = u_str(self.txt_endpoint.Text).strip()
        selected_ep = u_str(self.selected_model_info.get("endpoint", u"")).strip()
        explicit_ep = curr_ep if (curr_ep and curr_ep != selected_ep) else u""

        new_entry = build_custom_model_entry(raw_m, base_url, explicit_endpoint=explicit_ep)
        new_entry["default_steps"] = from_decimal_int(self.num_steps.Value, 4)
        new_entry["default_guidance"] = from_decimal_float(self.num_guidance.Value, 1.0)

        p_name, prof_obj = self._get_active_profile_dict()
        c_list = prof_obj.get("custom_models", [])
        updated = False
        for i, existing in enumerate(c_list):
            if isinstance(existing, dict) and u_str(existing.get("id", u"")).lower() == raw_m.lower():
                c_list[i] = new_entry
                updated = True
                break
        if not updated:
            c_list.insert(0, new_entry)
        prof_obj["custom_models"] = c_list
        prof_obj["last_model"] = new_entry["id"]
        save_profiles_data(self.profiles_data)

        self._refresh_models_list(auto_startup=True)
        self.log_step(
            u"Model '{}' saved to profile '{}' (endpoint: {})".format(new_entry["id"], p_name, new_entry["endpoint"]),
            progress_val=0,
            status_color=self.col_success,
        )

    def _on_remove_custom_model_click(self, sender, args):
        target_id = u_str(self.txt_custom_model.Text).strip() or u_str(self.selected_model_info.get("id", u"")).strip()
        if not target_id:
            return
        p_name, prof_obj = self._get_active_profile_dict()
        c_list = prof_obj.get("custom_models", [])
        new_c_list = [
            m for m in c_list
            if not (isinstance(m, dict) and u_str(m.get("id", u"")).lower() == target_id.lower())
        ]
        if len(new_c_list) < len(c_list):
            prof_obj["custom_models"] = new_c_list
            save_profiles_data(self.profiles_data)
            self.txt_custom_model.Text = u""
            self._refresh_models_list(auto_startup=True)
            self.log_step(u"Custom model '{}' removed from profile '{}'".format(target_id, p_name), progress_val=0)
        else:
            self.log_step(u"Model '{}' is a built-in catalog model (only custom ★ models can be removed)".format(target_id), progress_val=0)

    # --------------------------------------------------------------------------
    # ЗАГРУЗКА И ВЫБОР МОДЕЛЕЙ
    # --------------------------------------------------------------------------
    def _on_fetch_models_click(self, sender, args):
        self._refresh_models_list(auto_startup=False)

    def _refresh_models_list(self, auto_startup=False):
        base_url = u_str(self.txt_base_url.Text).strip() or u"https://api.chutes.ai"
        api_key = u_str(self.txt_api_key.Text).strip()
        _, prof_obj = self._get_active_profile_dict()
        custom_models = prof_obj.get("custom_models", [])

        if not auto_startup:
            self.log_step(
                u"Querying available image models from provider ({})...".format(base_url),
                progress_val=0,
                status_color=self.col_accent,
            )

        models, note = fetch_provider_image_models(
            base_url,
            api_key,
            custom_models=custom_models,
            fetch_online=(not auto_startup),
        )
        self.available_models = models
        self.lst_models.Items.Clear()
        for m in self.available_models:
            prefix = u"★ " if m.get("owner") == u"custom" or m.get("is_custom") else u""
            self.lst_models.Items.Add(prefix + u_str(m["id"]))

        target_idx = 0
        last_model_id = u_str(prof_obj.get("last_model", u"Qwen-Image-Edit-2511"))
        for i, m in enumerate(self.available_models):
            if m["id"].lower() == last_model_id.lower() or m["slug"].lower() == last_model_id.lower():
                target_idx = i
                break
        if self.lst_models.Items.Count > 0:
            self.lst_models.SelectedIndex = target_idx
        self.lbl_models_status.Text = u"Models: {} ({})".format(len(self.available_models), note)
        if not auto_startup:
            self.log_step(
                u"Models list updated ({} total, {})".format(len(self.available_models), note),
                progress_val=0,
                status_color=self.col_success,
            )

    def _on_model_selected(self, sender, args):
        idx = self.lst_models.SelectedIndex
        if idx < 0 or idx >= len(self.available_models):
            return
        m = self.available_models[idx]
        self.selected_model_info = m
        self.txt_endpoint.Text = u_str(m.get("endpoint", u""))
        self.txt_custom_model.Text = u_str(m.get("id", u""))
        is_edit_model = is_model_img2img(m, m.get("endpoint", u""))
        self.chk_send_image.Checked = bool(is_edit_model)

        def_steps = int(m.get("default_steps", 4))
        def_cfg = float(m.get("default_guidance", 1.0 if is_edit_model else 3.5))
        self._syncing_params = True
        try:
            self.num_steps.Value = to_decimal(max(1, min(100, def_steps)))
            self.trk_steps.Value = max(1, min(100, def_steps))
            self.num_guidance.Value = to_decimal(max(0.0, min(20.0, def_cfg)))
            self.trk_guidance.Value = max(0, min(200, int(round(def_cfg * 10.0))))
        except Exception:
            pass
        self._syncing_params = False

        if not self._is_initializing:
            self.log_step(
                u"Selected model: {}  |  {}".format(u_str(m.get("id")), u_str(m.get("description", u""))),
                progress_val=0,
            )

    # --------------------------------------------------------------------------
    # УНИВЕРСАЛЬНАЯ ЛОГИКА 3 ВХОДНЫХ СЛОТОВ (БЕЗ АВТОПЕЧАТИ ВИДА ПРИ ОТКРЫТИИ)
    # --------------------------------------------------------------------------
    def _init_all_slots(self, init_slot1_in, init_slot2_in, init_slot3_in):
        if init_slot1_in is not None:
            self._apply_initial_input_to_slot(0, init_slot1_in)
        elif len(self.all_views) > 0:
            self._assign_view_to_slot(0, self.all_views[0], enable_slot=True, render_now=False)
        if init_slot2_in is not None:
            self._apply_initial_input_to_slot(1, init_slot2_in)
        if init_slot3_in is not None:
            self._apply_initial_input_to_slot(2, init_slot3_in)

        self._rebuild_all_slot_combos()

        for s_idx in range(3):
            slot = self.slots[s_idx]
            if slot["enabled"] and slot["source_type"] == "file":
                self._refresh_slot_preview(s_idx)
            else:
                self._sync_slot_visual_state(s_idx)

        self._update_active_slots_summary()

    def _apply_initial_input_to_slot(self, s_idx, raw_input):
        if isinstance(raw_input, list) and len(raw_input) > 0:
            raw_input = raw_input[0]

        if isinstance(raw_input, STRING_TYPES):
            s_val = u_str(raw_input).strip()
            if s_val and File.Exists(s_val):
                self._assign_file_to_slot(s_idx, s_val, enable_slot=True, render_now=False)
                return
            if s_val:
                s_low = s_val.lower()
                for v_item in self.all_views:
                    if v_item["name"].lower() == s_low or v_item["label"].lower() == s_low:
                        self._assign_view_to_slot(s_idx, v_item, enable_slot=True, render_now=False)
                        return
        elif raw_input is not None:
            try:
                unwrapped = UnwrapElement(raw_input)
                target_id = get_element_id_int(unwrapped.Id)
                for v_item in self.all_views:
                    if get_element_id_int(v_item["view"].Id) == target_id:
                        self._assign_view_to_slot(s_idx, v_item, enable_slot=True, render_now=False)
                        return
            except Exception:
                pass

    def _assign_view_to_slot(self, s_idx, v_item, enable_slot=True, render_now=True):
        slot = self.slots[s_idx]
        slot["source_type"] = "view"
        slot["view_obj"] = v_item["view"]
        slot["view_id"] = get_element_id_int(v_item["view"].Id)
        slot["view_name"] = u_str(v_item["name"])
        slot["file_path"] = u""
        slot["preview_path"] = u""
        if enable_slot:
            slot["enabled"] = True
        if render_now and not self._is_initializing:
            self._refresh_slot_preview(s_idx)
        self._sync_slot_visual_state(s_idx)
        self._update_active_slots_summary()

    def _assign_file_to_slot(self, s_idx, file_path, enable_slot=True, render_now=True):
        if not file_path or not File.Exists(file_path):
            return
        slot = self.slots[s_idx]
        slot["source_type"] = "file"
        slot["file_path"] = u_str(file_path)
        slot["preview_path"] = u_str(file_path)
        slot["view_obj"] = None
        slot["view_id"] = -1
        slot["view_name"] = u""
        if enable_slot:
            slot["enabled"] = True
        self._rebuild_slot_combo(s_idx)
        if render_now:
            self._refresh_slot_preview(s_idx)
        self._sync_slot_visual_state(s_idx)
        self._update_active_slots_summary()

    def _clear_slot(self, s_idx):
        slot = self.slots[s_idx]
        slot["enabled"] = False
        slot["source_type"] = "none"
        slot["view_obj"] = None
        slot["view_id"] = -1
        slot["view_name"] = u""
        slot["file_path"] = u""
        slot["preview_path"] = u""

        pic = self.slot_pic_boxes[s_idx]
        if pic.Image is not None:
            try:
                pic.Image.Dispose()
            except Exception:
                pass
            pic.Image = None

        self._rebuild_slot_combo(s_idx)
        self._sync_slot_visual_state(s_idx)
        self._update_active_slots_summary()
        if not self._is_initializing:
            self.log_step(u"Scene #{} cleared and set to Inactive".format(s_idx + 1), progress_val=0)

    def _sync_slot_visual_state(self, s_idx):
        slot = self.slots[s_idx]
        is_on = bool(slot["enabled"]) and (slot["source_type"] in ("view", "file"))

        self._suppress_slot_events = True
        try:
            self.slot_checkboxes[s_idx].Checked = is_on
        finally:
            self._suppress_slot_events = False

        self.slot_checkboxes[s_idx].ForeColor = self.col_text if is_on else self.col_muted
        self.slot_row_labels[s_idx].ForeColor = self.col_text if is_on else self.col_muted

        pic = self.slot_pic_boxes[s_idx]
        ph = self.slot_placeholders[s_idx]
        pic.BackColor = self.col_slot_active if is_on else self.col_slot_inactive
        try:
            ph.BackColor = pic.BackColor
        except Exception:
            pass

        if slot["source_type"] == "view" and slot["view_name"] and pic.Image is None:
            ph.Text = u"Revit View: «{}»\nClick to render preview or press START".format(
                slot["view_name"]
            )
            ph.Visible = True
        elif pic.Image is None:
            default_ph = [
                u"Inactive\nSelect a view in Scene #1 or click File...",
                u"Inactive\nSelect a view in Scene #2 or click File...",
                u"Inactive\nSelect a view in Scene #3 or click File...",
            ]
            ph.Text = default_ph[s_idx]
            ph.Visible = True
        else:
            ph.Visible = False

        if slot["source_type"] == "file" and slot["file_path"]:
            self.slot_checkboxes[s_idx].Text = u"{}. Scene #{} [File: {}]".format(
                s_idx + 1, s_idx + 1, Path.GetFileName(slot["file_path"])
            )
        elif slot["source_type"] == "view" and slot["view_name"]:
            self.slot_checkboxes[s_idx].Text = u"{}. Scene #{} [View: {}]".format(
                s_idx + 1, s_idx + 1, slot["view_name"]
            )
        else:
            default_titles = [
                u"1. Scene #1 (Primary)",
                u"2. Scene #2 (Optional)",
                u"3. Scene #3 (Optional)",
            ]
            self.slot_checkboxes[s_idx].Text = default_titles[s_idx]

    def _rebuild_all_slot_combos(self):
        for s_idx in range(3):
            self._rebuild_slot_combo(s_idx)

    def _rebuild_slot_combo(self, s_idx):
        cmb = self.slot_combos[s_idx]
        slot = self.slots[s_idx]

        self._suppress_slot_events = True
        try:
            cmb.Items.Clear()
            cmb.Items.Add(NONE_VIEW_LABEL)

            selected_combo_idx = 0
            file_item_offset = 0
            if slot["source_type"] == "file" and slot["file_path"]:
                file_label = u"[File] " + Path.GetFileName(slot["file_path"])
                cmb.Items.Add(file_label)
                selected_combo_idx = 1
                file_item_offset = 1

            for i, v_item in enumerate(self.filtered_views):
                cmb.Items.Add(u_str(v_item["label"]))
                if slot["source_type"] == "view" and get_element_id_int(v_item["view"].Id) == slot["view_id"]:
                    selected_combo_idx = 1 + file_item_offset + i

            if (
                slot["source_type"] == "view"
                and slot["view_id"] != -1
                and selected_combo_idx == 0
                and slot["view_name"]
            ):
                keep_label = u"[Selected View] " + slot["view_name"]
                cmb.Items.Insert(1, keep_label)
                selected_combo_idx = 1

            cmb.SelectedIndex = selected_combo_idx
        finally:
            self._suppress_slot_events = False

    def _refresh_slot_preview(self, s_idx):
        slot = self.slots[s_idx]
        pic = self.slot_pic_boxes[s_idx]
        ph = self.slot_placeholders[s_idx]

        if slot["source_type"] == "file":
            f_path = slot["file_path"]
            if not f_path or not File.Exists(f_path):
                return
            try:
                img = load_image_unlocked(f_path)
                if img is not None:
                    if pic.Image is not None:
                        pic.Image.Dispose()
                    pic.Image = img
                    slot["preview_path"] = f_path
                    if s_idx == 0:
                        self.source_image_path = f_path
                    ph.Visible = False
                    self._sync_slot_visual_state(s_idx)
                    self._recalc_auto_width_preview()
                    if not self._is_initializing:
                        self.log_step(
                            u"Scene #{}: loaded file '{}' ({}x{} px)".format(
                                s_idx + 1, Path.GetFileName(f_path), img.Width, img.Height
                            ),
                            progress_val=0,
                        )
            except Exception as ex:
                self.log_step(u"Scene #{}: failed to read file — {}".format(s_idx + 1, u_str(ex)), progress_val=0)

        elif slot["source_type"] == "view":
            if self._is_initializing:
                return
            target_view = slot["view_obj"]
            if target_view is None or self.doc is None:
                return
            preview_px = max(640, min(1536, from_decimal_int(self.num_size.Value, 1024)))
            try:
                prefix_str = u"preview_slot{}".format(s_idx + 1)
                preview_path = self.revit_invoker.run(
                    lambda: export_revit_view_to_png(
                        self.doc,
                        target_view,
                        self.preview_temp_dir,
                        pixel_size=preview_px,
                        file_prefix=prefix_str,
                    ),
                    force_direct=False,
                )
                img = load_image_unlocked(preview_path)
                if img is not None:
                    if pic.Image is not None:
                        pic.Image.Dispose()
                    pic.Image = img
                    slot["preview_path"] = preview_path
                    if s_idx == 0:
                        self.source_image_path = preview_path
                    ph.Visible = False
                    self._sync_slot_visual_state(s_idx)
                    self._recalc_auto_width_preview()
                    self.log_step(
                        u"Scene #{}: view preview updated for '{}' ({}x{} px)".format(
                            s_idx + 1, slot["view_name"], img.Width, img.Height
                        ),
                        progress_val=0,
                    )
            except Exception as ex:
                self.log_step(
                    u"Scene #{}: failed to render preview for '{}' — {}".format(
                        s_idx + 1, slot["view_name"], u_str(ex)
                    ),
                    progress_val=0,
                )

    # --------------------------------------------------------------------------
    # ОБРАБОТЧИКИ СОБЫТИЙ СЛОТОВ 1..3 И ПОИСКА ВИДОВ
    # --------------------------------------------------------------------------
    def _on_view_search_changed(self, sender, args):
        q = u_str(self.txt_view_search.Text).strip().lower()
        if q:
            self.filtered_views = [
                v for v in self.all_views
                if (q in v["name"].lower()) or (q in v["label"].lower())
            ]
        else:
            self.filtered_views = list(self.all_views)
        self._rebuild_all_slot_combos()

    def _on_clear_view_search(self, sender, args):
        if u_str(self.txt_view_search.Text) != u"":
            self.txt_view_search.Text = u""

    def _on_toggle_all_views(self, sender, args):
        inc_2d = bool(self.chk_all_views.Checked)
        try:
            self.all_views = self.revit_invoker.run(
                lambda: collect_project_views(self.doc, include_non_3d=inc_2d)
            )
        except Exception:
            self.all_views = collect_project_views(self.doc, include_non_3d=inc_2d)
        self._on_view_search_changed(None, None)

    def _make_slot_combo_handler(self, s_idx):
        def _handler(sender, args):
            if self._suppress_slot_events or self._is_initializing:
                return
            cmb = self.slot_combos[s_idx]
            sel_text = u_str(cmb.SelectedItem or u"")
            if cmb.SelectedIndex <= 0 or sel_text == NONE_VIEW_LABEL:
                self._clear_slot(s_idx)
                return
            if sel_text.startswith(u"[File]") or sel_text.startswith(u"[Selected View]"):
                return

            matched_v = None
            for v_item in self.filtered_views:
                if u_str(v_item["label"]) == sel_text:
                    matched_v = v_item
                    break
            if matched_v is not None:
                self._assign_view_to_slot(s_idx, matched_v, enable_slot=True, render_now=True)
                self._rebuild_slot_combo(s_idx)

        return _handler

    def _make_slot_file_handler(self, s_idx):
        def _handler(sender, args):
            self._pick_file_for_slot(s_idx)

        return _handler

    def _make_slot_clear_handler(self, s_idx):
        def _handler(sender, args):
            self._clear_slot(s_idx)

        return _handler

    def _make_slot_chk_handler(self, s_idx):
        def _handler(sender, args):
            if self._suppress_slot_events or self._is_initializing:
                return
            chk = self.slot_checkboxes[s_idx]
            slot = self.slots[s_idx]
            want_on = bool(chk.Checked)
            if want_on and slot["source_type"] == "none":
                picked = self._pick_file_for_slot(s_idx)
                if not picked and slot["source_type"] == "none":
                    self._suppress_slot_events = True
                    chk.Checked = False
                    self._suppress_slot_events = False
                    return
            else:
                slot["enabled"] = want_on
                self._sync_slot_visual_state(s_idx)
                self._update_active_slots_summary()

        return _handler

    def _make_slot_placeholder_click_handler(self, s_idx):
        def _handler(sender, args):
            slot = self.slots[s_idx]
            if slot["source_type"] in ("view", "file"):
                slot["enabled"] = True
                self._refresh_slot_preview(s_idx)
            else:
                self._pick_file_for_slot(s_idx)

        return _handler

    def _make_slot_pic_click_handler(self, s_idx):
        def _handler(sender, args):
            slot = self.slots[s_idx]
            pic = self.slot_pic_boxes[s_idx]
            p_path = slot["preview_path"] or slot["file_path"]
            if pic.Image is not None or (p_path and File.Exists(p_path)):
                show_full_image_window(
                    p_path,
                    u"Scene #{}: {}".format(s_idx + 1, self._get_slot_short_description(s_idx)),
                    live_bitmap=pic.Image,
                )
            elif slot["source_type"] == "view":
                self._refresh_slot_preview(s_idx)
            else:
                self._pick_file_for_slot(s_idx)

        return _handler

    def _pick_file_for_slot(self, s_idx):
        dlg = OpenFileDialog()
        dlg.Title = u"Select Image File for Scene #{}".format(s_idx + 1)
        dlg.Filter = u"Images (*.png;*.jpg;*.jpeg;*.bmp;*.webp)|*.png;*.jpg;*.jpeg;*.bmp;*.webp|All Files (*.*)|*.*"

        slot = self.slots[s_idx]
        init_dir = u""
        if slot["file_path"] and File.Exists(slot["file_path"]):
            init_dir = Path.GetDirectoryName(slot["file_path"])
        if not init_dir or not Directory.Exists(init_dir):
            out_dir_curr = u_str(self.txt_out_dir.Text).strip()
            if out_dir_curr:
                if not Directory.Exists(out_dir_curr):
                    try:
                        Directory.CreateDirectory(out_dir_curr)
                    except Exception:
                        pass
                if Directory.Exists(out_dir_curr):
                    init_dir = out_dir_curr
        if init_dir and Directory.Exists(init_dir):
            dlg.InitialDirectory = init_dir

        if dlg.ShowDialog() == DialogResult.OK:
            picked_path = u_str(dlg.FileName)
            self._assign_file_to_slot(s_idx, picked_path, enable_slot=True, render_now=True)
            return picked_path
        return u""

    # --------------------------------------------------------------------------
    # ПРОСМОТР РЕЗУЛЬТАТА И ОКНО СРАВНЕНИЯ «ДО / ПОСЛЕ»
    # --------------------------------------------------------------------------
    def _on_result_preview_click(self, sender, args):
        if self.pic_result.Image is not None or (self.result_image_path and File.Exists(self.result_image_path)):
            show_full_image_window(
                self.result_image_path,
                u"AI Render Result — " + u_str(self.selected_model_info.get("id", u"Chutes.ai")),
                live_bitmap=self.pic_result.Image,
            )

    def _on_open_vault_dir(self, sender, args):
        out_dir_curr = u_str(self.txt_out_dir.Text).strip()
        if not out_dir_curr:
            desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop)
            out_dir_curr = Path.Combine(desktop, u"Chutes_Renders")
            self.txt_out_dir.Text = out_dir_curr
        open_folder_in_explorer(out_dir_curr)

    def _on_browse_out_dir(self, sender, args):
        dlg = FolderBrowserDialog()
        dlg.Description = u"Select output folder (Vault) for saving AI renders"
        dlg.SelectedPath = u_str(self.txt_out_dir.Text)
        if dlg.ShowDialog() == DialogResult.OK:
            self.txt_out_dir.Text = u_str(dlg.SelectedPath)

    def _on_open_compare_click(self, sender, args):
        inputs_for_cmp = []
        seen_slots = set()

        for s_idx in range(3):
            slot = self.slots[s_idx]
            p_path = slot["preview_path"] or slot["file_path"]
            if slot["enabled"] and p_path and File.Exists(p_path):
                inputs_for_cmp.append(
                    (u"Scene #{} ({})".format(s_idx + 1, self._get_slot_short_description(s_idx)), p_path)
                )
                seen_slots.add(s_idx)

        for s_idx in range(3):
            if s_idx in seen_slots:
                continue
            slot = self.slots[s_idx]
            p_path = slot["preview_path"] or slot["file_path"]
            if p_path and File.Exists(p_path):
                inputs_for_cmp.append(
                    (u"Scene #{} ({})".format(s_idx + 1, self._get_slot_short_description(s_idx)), p_path)
                )

        if self.result_image_path and File.Exists(self.result_image_path):
            show_comparison_window(
                inputs_for_cmp,
                self.result_image_path,
                self._get_primary_label(),
                u_str(self.txt_prompt.Text),
                u_str(self.selected_model_info.get("id", u"Chutes.ai")),
            )

    def _get_primary_label(self):
        for s_idx in range(3):
            slot = self.slots[s_idx]
            if slot["enabled"] and slot["source_type"] in ("view", "file"):
                return self._get_slot_short_description(s_idx)
        return u"AI Render"

    def _get_scene1_name_for_file(self):
        """Возвращает имя вида или файла из Scene #1 (или следующего активного слота) для имени выходного файла."""
        slot0 = self.slots[0]
        if slot0["source_type"] == "file" and slot0["file_path"]:
            return Path.GetFileNameWithoutExtension(slot0["file_path"])
        if slot0["source_type"] == "view" and slot0["view_name"]:
            return slot0["view_name"]
        for s_idx in (1, 2):
            st = self.slots[s_idx]
            if st["enabled"]:
                if st["source_type"] == "file" and st["file_path"]:
                    return Path.GetFileNameWithoutExtension(st["file_path"])
                if st["source_type"] == "view" and st["view_name"]:
                    return st["view_name"]
        return u"Scene1"

    # --------------------------------------------------------------------------
    # ЗАПУСК ЭКСПОРТА АКТИВНЫХ КАДРОВ (1..3) И AI-ГЕНЕРАЦИИ ("START | НАЧАТЬ")
    # --------------------------------------------------------------------------
    def _on_generate_click(self, sender, args):
        api_key = u_str(self.txt_api_key.Text).strip()
        if not api_key:
            MessageBox.Show(
                u"Please enter your API Key (e.g. cpk_...) in section I and click Save if needed",
                u"API Key Required",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning,
            )
            return

        endpoint_url = u_str(self.txt_endpoint.Text).strip()
        if not endpoint_url:
            endpoint_url = u"https://vonkaiser-qwen-image-edit-2511.chutes.ai/generate"
            self.txt_endpoint.Text = endpoint_url

        out_dir = u_str(self.txt_out_dir.Text).strip()
        if not out_dir:
            desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop)
            out_dir = Path.Combine(desktop, u"Chutes_Renders")
            self.txt_out_dir.Text = out_dir

        base_size_px = from_decimal_int(self.num_size.Value, 1024)
        manual_w_px = from_decimal_int(self.num_width.Value, 1024)
        steps_val = from_decimal_int(self.num_steps.Value, 4)
        guidance_val = from_decimal_float(self.num_guidance.Value, 1.0)
        seed_val = from_decimal_int(self.num_seed.Value, 42)
        prompt_text = u_str(self.txt_prompt.Text).strip()
        neg_prompt_text = u_str(self.txt_neg_prompt.Text).strip()
        use_sys_prompt = bool(self.profiles_data.get("use_system_prompt", False))
        sys_prompt_text = u_str(self.profiles_data.get("system_prompt", u"")).strip()

        model_info_curr = dict(self.selected_model_info)
        model_info_curr["endpoint"] = endpoint_url
        custom_m_name = u_str(self.txt_custom_model.Text).strip()
        if custom_m_name:
            model_info_curr["id"] = custom_m_name

        model_accepts_img = is_model_img2img(model_info_curr, endpoint_url)
        send_img_master = bool(self.chk_send_image.Checked) and model_accepts_img

        try:
            p_name, prof_obj = self._get_active_profile_dict()
            prof_obj["last_model"] = u_str(self.selected_model_info.get("id", u""))
            save_profiles_data(self.profiles_data)
        except Exception:
            pass

        self.btn_generate.Enabled = False
        self.Cursor = Cursors.WaitCursor

        try:
            if not Directory.Exists(out_dir):
                Directory.CreateDirectory(out_dir)

            b64_images_list = []
            active_labels = []
            exported_slot_paths = [u"", u"", u""]
            dimension_ref_path = u""

            export_px = max(base_size_px, manual_w_px) if self.manual_width_enabled else base_size_px

            # ЭТАП 1: Подготовка всех отмеченных галочками входных слотов (1..3)
            if send_img_master:
                for s_idx in range(3):
                    slot = self.slots[s_idx]
                    if not slot["enabled"] or slot["source_type"] == "none":
                        continue

                    if slot["source_type"] == "view":
                        target_view = slot["view_obj"]
                        if target_view is None or self.doc is None:
                            raise Exception(u"Scene #{}: selected Revit view is unavailable".format(s_idx + 1))

                        self.log_step(
                            u"[1/4] Scene #{}: exporting Revit view '{}' ({} px)...".format(
                                s_idx + 1, slot["view_name"], export_px
                            ),
                            progress_val=10 + s_idx * 8,
                            status_color=self.col_accent,
                        )
                        prefix_str = u"slot{}_{}".format(
                            s_idx + 1, sanitize_filename_part(slot["view_name"], u"view")
                        )
                        exp_path = self.revit_invoker.run(
                            lambda: export_revit_view_to_png(
                                self.doc,
                                target_view,
                                self.preview_temp_dir,
                                pixel_size=export_px,
                                file_prefix=prefix_str,
                            )
                        )
                        slot["preview_path"] = exp_path
                        exported_slot_paths[s_idx] = exp_path
                        if not dimension_ref_path:
                            dimension_ref_path = exp_path

                        img_upd = load_image_unlocked(exp_path)
                        if img_upd is not None:
                            pic_box = self.slot_pic_boxes[s_idx]
                            if pic_box.Image is not None:
                                pic_box.Image.Dispose()
                            pic_box.Image = img_upd
                            self.slot_placeholders[s_idx].Visible = False

                        b64_images_list.append(file_to_base64_str(exp_path, max_side_limit=export_px))
                        active_labels.append(u"#{}:View({})".format(s_idx + 1, slot["view_name"]))

                    elif slot["source_type"] == "file":
                        f_path = slot["file_path"]
                        if not f_path or not File.Exists(f_path):
                            raise Exception(u"Scene #{}: file '{}' not found".format(s_idx + 1, f_path))

                        self.log_step(
                            u"[1/4] Scene #{}: reading and optimizing file '{}'...".format(
                                s_idx + 1, Path.GetFileName(f_path)
                            ),
                            progress_val=10 + s_idx * 8,
                            status_color=self.col_accent,
                        )
                        slot["preview_path"] = f_path
                        exported_slot_paths[s_idx] = f_path
                        if not dimension_ref_path:
                            dimension_ref_path = f_path

                        b64_images_list.append(file_to_base64_str(f_path, max_side_limit=max(1280, export_px)))
                        active_labels.append(u"#{}:File({})".format(s_idx + 1, Path.GetFileName(f_path)))

            # Если выбрана текстовая модель (Txt2Img), но в слотах уже есть превью — берём его для пропорций кадра
            if not dimension_ref_path:
                for s_idx in range(3):
                    slot = self.slots[s_idx]
                    cand_p = slot["preview_path"] or slot["file_path"]
                    if slot["enabled"] and cand_p and File.Exists(cand_p):
                        dimension_ref_path = cand_p
                        break

            # Если выбрана Img2Img-модель (Qwen-Image-Edit-2511), но кадр ещё не был отправлен — проверяем наличие
            if model_accepts_img and len(b64_images_list) == 0:
                raise Exception(
                    u"Editing model '{}' requires at least one active scene in section III (Scene #1) and Send Scene Images [Base64] enabled".format(
                        u_str(model_info_curr.get("id", u"Qwen-Image-Edit-2511"))
                    )
                )

            if exported_slot_paths[0]:
                self.source_image_path = exported_slot_paths[0]
            elif dimension_ref_path:
                self.source_image_path = dimension_ref_path

            # ЭТАП 2: Вычисление размеров кадра (кратно 64, в диапазоне 512..2048 px)
            if self.manual_width_enabled:
                target_w = int(round(float(manual_w_px) / 64.0) * 64)
                target_h = int(round(float(base_size_px) / 64.0) * 64)
                target_w = max(512, min(2048, target_w))
                target_h = max(512, min(2048, target_h))
            else:
                if dimension_ref_path and File.Exists(dimension_ref_path):
                    target_w, target_h = calc_target_dimensions(dimension_ref_path, base_size_px)
                else:
                    side_c = max(512, min(2048, int(round(float(base_size_px) / 64.0) * 64)))
                    target_w, target_h = side_c, side_c
                try:
                    self.num_width.Value = to_decimal(target_w)
                except Exception:
                    pass

            self.log_step(
                u"[2/4] Resolution: {}x{} px | CFG: {} | Steps: {} | Seed: {} | Scenes: {}".format(
                    target_w, target_h, guidance_val, steps_val, seed_val, len(b64_images_list)
                ),
                progress_val=38,
                status_color=self.col_accent,
            )

            payload = build_generation_payload(
                model_info_curr,
                prompt_text,
                b64_images_list,
                target_w,
                target_h,
                steps_val,
                guidance_val=guidance_val,
                seed_val=seed_val,
                neg_prompt_text=neg_prompt_text,
                system_prompt_text=sys_prompt_text,
                use_system_prompt=use_sys_prompt,
                send_source_image=(send_img_master and len(b64_images_list) > 0),
            )

            # ЭТАП 3: Фоновая отправка одиночного HTTP-запроса (без авто-повторов)
            model_id = u_str(model_info_curr.get("id", u"Chutes.ai"))
            imgs_info_str = u", ".join(active_labels) if active_labels else u"txt2img"
            self.log_step(
                u"[3/4] Sending to {} ({}x{}, steps={}, cfg={}, seed={}, mode: [{}])...".format(
                    model_id, target_w, target_h, steps_val, guidance_val, seed_val, imgs_info_str
                ),
                progress_val=50,
                status_color=self.col_accent,
            )

            max_busy_attempts = 4 if bool(self.chk_retry_busy.Checked) else 1
            t_total_start = time.time()
            http_status = -1
            result_val = u""

            for attempt_idx in range(1, max_busy_attempts + 1):
                worker_state = {"done": False, "status": -1, "result": u""}

                scene1_label_for_file = self._get_scene1_name_for_file()
                output_base_name = build_render_output_base_name(model_id, scene1_label_for_file, seed_val)

                def _bg_request():
                    st, res = send_image_generation_request(
                        endpoint_url,
                        api_key,
                        payload,
                        out_dir,
                        model_info=model_info_curr,
                        base_file_name=output_base_name,
                    )
                    worker_state["status"] = st
                    worker_state["result"] = res
                    worker_state["done"] = True

                t_attempt = time.time()
                bg_thread = Thread(ThreadStart(_bg_request))
                bg_thread.IsBackground = True
                bg_thread.Start()

                while not worker_state["done"]:
                    elapsed = round(time.time() - t_total_start, 1)
                    dyn_prog = min(95, 50 + int(elapsed * 2.5))
                    self.progress_bar.Value = dyn_prog
                    att_note = (
                        u" [attempt {}/{}]".format(attempt_idx, max_busy_attempts)
                        if max_busy_attempts > 1 and attempt_idx > 1
                        else u""
                    )
                    self.lbl_stage.Text = u"[3/4] Generating on {}{} ({}x{})... Elapsed {:.1f}s".format(
                        model_id, att_note, target_w, target_h, elapsed
                    )
                    Application.DoEvents()
                    Thread.Sleep(100)

                http_status = worker_state["status"]
                result_val = worker_state["result"]

                is_busy_500 = (
                    http_status in (500, 502, 503, 504, 429)
                    and (
                        u"no infrastructure available" in u_str(result_val).lower()
                        or u"busy" in u_str(result_val).lower()
                        or u"capacity" in u_str(result_val).lower()
                        or http_status in (502, 503, 504, 429)
                    )
                )
                if is_busy_500 and attempt_idx < max_busy_attempts:
                    wait_sec = 2.5
                    self.log_step(
                        u"GPU worker for '{}' is busy (HTTP {}), waiting {}s before reconnect ({}/{})...".format(
                            model_id, http_status, wait_sec, attempt_idx + 1, max_busy_attempts
                        ),
                        progress_val=55,
                        status_color=self.col_accent,
                    )
                    w_t0 = time.time()
                    while (time.time() - w_t0) < wait_sec:
                        Application.DoEvents()
                        Thread.Sleep(80)
                    continue
                break

            elapsed_sec = round(time.time() - t_total_start, 2)

            # ЭТАП 4: Обработка результата и показ в Превью 4
            if http_status == 200 and File.Exists(u_str(result_val)):
                self.result_image_path = u_str(result_val)
                res_img = load_image_unlocked(self.result_image_path)
                if res_img is not None:
                    if self.pic_result.Image is not None:
                        self.pic_result.Image.Dispose()
                    self.pic_result.Image = res_img

                self.btn_open_compare.Enabled = True
                self._update_compare_btn_appearance()
                self.execution_succeeded = True

                self.status_message = u"HTTP 200 | model: {} | imgs: {} | {}x{} | steps: {} | cfg: {} | seed: {} | {}s".format(
                    model_id, len(b64_images_list), target_w, target_h, steps_val, guidance_val, seed_val, elapsed_sec
                )
                self.meta_result = {
                    "version": u"3.2",
                    "model": model_id,
                    "endpoint": endpoint_url,
                    "prompt": prompt_text,
                    "negative_prompt": neg_prompt_text,
                    "system_prompt_enabled": use_sys_prompt,
                    "width": target_w,
                    "height": target_h,
                    "manual_width_mode": self.manual_width_enabled,
                    "num_inference_steps": steps_val,
                    "guidance_scale": guidance_val,
                    "seed": seed_val,
                    "elapsed_sec": elapsed_sec,
                    "images_sent_count": len(b64_images_list),
                    "active_inputs": active_labels,
                    "slot1_image": exported_slot_paths[0],
                    "slot2_image": exported_slot_paths[1],
                    "slot3_image": exported_slot_paths[2],
                    "result_image": self.result_image_path,
                }
                self.lbl_preview_meta.Text = u"Completed in {}s ({}x{}, seed={}, scenes: {}/3) — click preview to enlarge".format(
                    elapsed_sec, target_w, target_h, seed_val, len(b64_images_list)
                )
                self.log_step(
                    u"[4/4] Completed — render saved to {} ({}s, scenes: {})".format(
                        self.result_image_path, elapsed_sec, len(b64_images_list)
                    ),
                    progress_val=100,
                    status_color=self.col_success,
                )
            else:
                self.status_message = u"HTTP {} | error: {}".format(http_status, u_str(result_val))
                self.meta_result = {
                    "version": u"3.2",
                    "model": model_id,
                    "endpoint": endpoint_url,
                    "error": u_str(result_val),
                }
                self.log_step(
                    u"Generation error (HTTP {}): {}".format(http_status, u_str(result_val)[:240]),
                    progress_val=0,
                    status_color=Color.FromArgb(220, 38, 38),
                )

        except Exception as ex:
            self.status_message = u"ERROR: {}".format(u_str(ex))
            self.log_step(u"Execution error: {}".format(u_str(ex)), progress_val=0, status_color=Color.FromArgb(220, 38, 38))
        finally:
            self.btn_generate.Enabled = True
            self.Cursor = Cursors.Default


# ==============================================================================
# 9. ТОЧКА ВХОДА НОДА DYNAMO (НЕМОДАЛЬНЫЙ ЗАПУСК ПАРАЛЛЕЛЬНО С REVIT)
# ==============================================================================

init_api_key = get_input(0, None)
init_slot1_in = get_input(1, None)
init_prompt = get_input(
    2,
    u"Convert this 3D CAD view into a photorealistic architectural render, preserve exact building contours and geometry, glass and concrete facade, sunny day",
)
init_base_url = get_input(3, u"https://api.chutes.ai")

desktop_dir = Environment.GetFolderPath(Environment.SpecialFolder.Desktop)
default_out_dir = Path.Combine(desktop_dir, u"Chutes_Renders")
init_out_dir = u_str(get_input(4, default_out_dir))

try:
    init_max_side = int(get_input(5, 1024))
except Exception:
    init_max_side = 1024

try:
    init_steps = int(get_input(6, 4))
except Exception:
    init_steps = 4

init_slot2_in = get_input(7, None)
init_slot3_in = get_input(8, None)

try:
    current_doc = DocumentManager.Instance.CurrentDBDocument
except Exception:
    current_doc = None

try:
    current_uiapp = DocumentManager.Instance.CurrentUIApplication
except Exception:
    current_uiapp = None

try:
    prev_form = AppDomain.CurrentDomain.GetData("DynamoChutesAI_ActiveForm")
    if prev_form is not None:
        prev_form.Close()
except Exception:
    pass

try:
    revit_invoker = RevitApiInvoker(current_uiapp)
    studio_form = ChutesRevitStudioForm(
        current_doc,
        revit_invoker,
        init_api_key,
        init_slot1_in,
        init_prompt,
        init_base_url,
        init_out_dir,
        init_max_side,
        init_steps,
        init_slot2_in,
        init_slot3_in,
    )
    AppDomain.CurrentDomain.SetData("DynamoChutesAI_ActiveForm", studio_form)
    studio_form.Show()

    OUT = [
        studio_form.result_image_path,
        studio_form.source_image_path,
        studio_form.status_message,
        studio_form.meta_result,
    ]
except Exception as main_ex:
    OUT = [u"", u"", u"UI ERROR: {}".format(u_str(main_ex)), {}]
