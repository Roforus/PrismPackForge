"""Normalize instance-based and ordinary game folders into one export input."""
import json
from pathlib import Path

from .common import PackError
from .game_runtime import version_token

LOADER_UIDS = {'Fabric':'net.fabricmc.fabric-loader', 'Forge':'net.minecraftforge',
               'NeoForge':'net.neoforged', 'Quilt':'org.quiltmc.quilt-loader'}


def read_source(folder: Path, minecraft=None, loader=None, loader_version=None):
    metadata = folder / 'mmc-pack.json'
    if metadata.is_file():
        components = json.loads(metadata.read_text('utf-8'))
        game = next((folder / p for p in ('minecraft','.minecraft') if (folder / p).is_dir()), None)
        if game is None:
            raise PackError('В экземпляре не найдена папка minecraft или .minecraft')
        return game, components
    if not minecraft or not loader:
        raise PackError('Для игровой папки укажите Minecraft и модлоадер (или Vanilla). '
                        'Версии возьмите из настроек исходного профиля лаунчера')
    mc = version_token(minecraft)
    components = [{'uid':'net.minecraft','version':mc}]
    if loader != 'Vanilla':
        if loader not in LOADER_UIDS or not loader_version:
            raise PackError('Укажите поддерживаемый модлоадер и его точную версию')
        components.append({'uid':LOADER_UIDS[loader],'version':version_token(loader_version)})
    return folder, {'formatVersion':1,'components':components}
