from os import path as ospath
from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE
from json import loads as jsonloads
from configparser import ConfigParser
from bot import GLOBAL_EXTENSION_FILTER, LOGGER, config_dict, remotes_multi
from bot.helper.ext_utils.bot_utils import cmd_exec, run_sync_to_async
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.ext_utils.exceptions import NotRclonePathFound
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.ext_utils.menu_utils import (
    Menus,
    rcloneListButtonMaker,
    rcloneListNextPage,
)
from bot.helper.telegram_helper.message_utils import (
    editMessage,
    sendMarkup,
    sendMessage,
)
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.ext_utils.rclone_data_holder import get_rclone_data, update_rclone_data


async def is_remote_selected(user_id, message):
    if CustomFilters.sudo_filter("", message):
        if DEFAULT_OWNER_REMOTE := config_dict.get("DEFAULT_OWNER_REMOTE"):
            update_rclone_data("MIRROR_SELECT_REMOTE", DEFAULT_OWNER_REMOTE, user_id)
            return True
    if config_dict.get("MULTI_RCLONE_CONFIG"):
        if get_rclone_data("MIRROR_SELECT_REMOTE", user_id):
            return True
        elif len(remotes_multi) > 0:
            return True
        else:
            await sendMessage(
                f"Select a cloud first, use /{BotCommands.MirrorSelectCommand[0]}",
                message,
            )
            return False
    else:
        return True


async def is_rclone_config(user_id, message, isLeech=False):
    if config_dict.get("MULTI_RCLONE_CONFIG"):
        path = f"rclone/{user_id}/rclone.conf"
        no_path_msg = "Send a rclone config file, use /files command"
    else:
        if CustomFilters.sudo(user_id):
            path = f"rclone/{user_id}/rclone.conf"
            no_path_msg = "Send a rclone config file, use /files command"
        else:
            path = f"rclone/rclone_global/rclone.conf"
            no_path_msg = "Rclone config file not found"

    if ospath.exists(path):
        return True
    else:
        if isLeech:
            return True
        await sendMessage(no_path_msg, message)
        return False


async def get_rclone_path(user_id, message=None):
    if config_dict.get("MULTI_RCLONE_CONFIG"):
        path = f"rclone/{user_id}/rclone.conf"
    else:
        if CustomFilters.sudo(user_id):
            path = f"rclone/{user_id}/rclone.conf"
        else:
            path = f"rclone/rclone_global/rclone.conf"

    if ospath.exists(path):
        return path
    else:
        await sendMessage("Rclone path not found", message)
        raise NotRclonePathFound(f"ERROR: Rclone path not found")


async def setRcloneFlags(cmd, type):
    cmd.extend(("--exclude", "*.{" + ",".join(GLOBAL_EXTENSION_FILTER) + "}"))
    if config_dict.get("SERVER_SIDE"):
        cmd.append("--drive-server-side-across-configs")
    if type == "copy":
        if flags := config_dict.get("RCLONE_COPY_FLAGS"):
            append_flags(flags, cmd)
    elif type == "upload":
        if flags := config_dict.get("RCLONE_UPLOAD_FLAGS"):
            append_flags(flags, cmd)
    elif type == "download":
        if flags := config_dict.get("RCLONE_DOWNLOAD_FLAGS"):
            append_flags(flags, cmd)


def append_flags(flags, cmd):
    rcflags = flags.split(",")
    for flag in rcflags:
        if ":" in flag:
            key, value = flag.split(":")
            cmd.extend((key, value))
        elif len(flag) > 0:
            cmd.append(flag)


async def is_gdrive_remote(remote, config_file):
    conf = ConfigParser()
    conf.read(config_file)
    is_gdrive = False
    if conf.get(remote, "type") == "drive":
        is_gdrive = True
    elif conf.get(remote, "type") == "crypt":
        remote_path = conf.get(remote, "remote")
        real_remote = remote_path.split(":")[0]
        if conf.get(real_remote, "type") == "drive":
            is_gdrive = True
    return is_gdrive


async def list_remotes(
    message, menu_type, remote_type="remote", is_second_menu=False, edit=False
):
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    else:
        user_id = message.from_user.id
    path = await get_rclone_path(user_id, message)
    conf = ConfigParser()
    conf.read(path)
    buttons = ButtonMaker()
    for remote in conf.sections():
        prev_icon = ""
        crypt_icon = ""
        is_crypt = False
        if conf.get(remote, "type") == "crypt":
            is_crypt = True
            crypt_icon = "🔐"
        if CustomFilters.sudo_filter("", message) and config_dict.get("MULTI_REMOTE_UP"):
            if remote in remotes_multi:
                prev_icon = "✅"
            buttons.cb_buildbutton(
                f"{prev_icon} {crypt_icon} 📁 {remote}",
                f"{menu_type}^{remote_type}^{remote}^{is_crypt}^{user_id}",
            )
        else:
            buttons.cb_buildbutton(
                f"{crypt_icon} 📁 {remote}",
                f"{menu_type}^{remote_type}^{remote}^{is_crypt}^{user_id}",
            )
    if menu_type == Menus.REMOTE_SELECT:
        msg = "Select cloud where you want to mirror the file"
    if menu_type == Menus.CLEANUP:
        msg = "Select cloud to delete trash"
    elif menu_type == Menus.STORAGE:
        msg = "Select cloud to view info"
    elif menu_type == Menus.MIRROR_SELECT:
        if config_dict.get("MULTI_REMOTE_UP"):
            msg = f"Select all clouds where you want to upload file"
            buttons.cb_buildbutton("🔄 Reset", f"{menu_type}^reset^{user_id}", "footer")
        else:
            remote = get_rclone_data("MIRROR_SELECT_REMOTE", user_id)
            dir = get_rclone_data("MIRROR_SELECT_BASE_DIR", user_id)
            msg = f"Select cloud where you want to store files\n\n<b>Path:</b><code>{remote}:{dir}</code>"
    elif menu_type == Menus.SYNC:
        msg = f"Select <b>{remote_type}</b> cloud"
        msg += "<b>\n\nNote</b>: Sync make source and destination identical, modifying destination only."
    else:
        msg = "Select cloud where your files are stored\n\n"
    if is_second_menu:
        msg = "Select folder where you want to copy"
    buttons.cb_buildbutton("✘ Close Menu", f"{menu_type}^close^{user_id}", "footer")
    if edit:
        await editMessage(msg, message, reply_markup=buttons.build_menu(2))
    else:
        await sendMarkup(msg, message, reply_markup=buttons.build_menu(2))


async def is_valid_path(remote, path, message):
    user_id = message.reply_to_message.from_user.id
    rc_path = await get_rclone_path(user_id, message)
    cmd = ["rclone", "lsjson", f"--config={rc_path}", f"{remote}:{path}"]
    process = await create_subprocess_exec(*cmd, stdout=PIPE)
    return_code = await process.wait()
    if return_code != 0:
        LOGGER.info("Error: Path not valid")
        return False
    else:
        return True


async def list_folder(
    message,
    rclone_remote,
    base_dir,
    menu_type,
    is_second_menu=False,
    is_crypt=False,
    edit=False,
):
    user_id = message.reply_to_message.from_user.id
    buttons = ButtonMaker()
    path = await get_rclone_path(user_id, message)
    msg = ""
    next_type = ""
    dir_callback = "remote_dir"
    file_callback = ""
    back_callback = "back"

    cmd = ["rclone", "lsjson", f"--config={path}", f"{rclone_remote}:{base_dir}"]

    if menu_type == Menus.LEECH:
        next_type = "next_leech"
        file_callback = "leech_file"
        try:
            cmd.extend(["--fast-list", "--no-modtime"])
            buttons.cb_buildbutton(
                "✅ Select this folder", f"{menu_type}^leech_folder^{user_id}"
            )
            msg = f"Select folder or file that you want to leech\n\n<b>Path:</b><code>{rclone_remote}:{base_dir}</code>"
        except KeyError:
            raise ValueError("Invalid key")
    elif menu_type == Menus.MIRROR_SELECT:
        rc_path = f"{rclone_remote}:{base_dir}"
        conf = ConfigParser()
        conf.read(path)
        if is_crypt:
            if (
                rclone_remote in conf.sections()
                and conf.get(rclone_remote, "type") == "crypt"
            ):
                rc_path = conf.get(rclone_remote, "remote")
                msg = f"Crypt Remote\n\n<b>Path:</b><code>{rc_path}</code>"
                buttons.cb_buildbutton("✅ Select", f"{menu_type}^close^{user_id}")
                buttons.cb_buildbutton("✅ Select", f"{menu_type}^close^{user_id}")
            else:
                raise ValueError("Invalid crypt remote configuration")
        else:
            buttons.cb_buildbutton("✅ Select", f"{menu_type}^close^{user_id}")
            msg = f"Select folder or file to mirror\n\n<b>Path:</b><code>{rc_path}</code>"
    else:
        next_type = "next_folder"
        file_callback = "mirror_file"
        msg = f"Select folder or file from <b>Path:</b><code>{rclone_remote}:{base_dir}</code>"

    process = await create_subprocess_exec(*cmd, stdout=PIPE)
    output, _ = await process.communicate()
    output = output.decode()
    items = jsonloads(output)
    buttons = ButtonMaker()

    for item in items:
        name = item.get("Name")
        if item.get("IsDir"):
            buttons.cb_buildbutton(
                f"📁 {name}",
                f"{menu_type}^{dir_callback}^{rclone_remote}^{base_dir}/{name}^{is_crypt}^{user_id}",
            )
        else:
            buttons.cb_buildbutton(
                f"📄 {name}",
                f"{menu_type}^{file_callback}^{rclone_remote}^{base_dir}/{name}^{is_crypt}^{user_id}",
            )

    if is_second_menu:
        buttons.cb_buildbutton("⬅️ Back", f"{menu_type}^{back_callback}^{rclone_remote}^{base_dir}^{is_crypt}^{user_id}", "footer")

    buttons.cb_buildbutton("✘ Close Menu", f"{menu_type}^close^{user_id}", "footer")
    if edit:
        await editMessage(msg, message, reply_markup=buttons.build_menu(2))
    else:
        await sendMarkup(msg, message, reply_markup=buttons.build_menu(2))
                
