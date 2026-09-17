# Дописывает в PATH те места, куда Docker Desktop кладёт команду docker.
# Подключается строкой `. "$(dirname "$0")/docker-path.sh"`.
#
# Полагаться на один PATH нельзя по двум причинам.
#
# Первая: при установке Docker Desktop спрашивает, куда положить команды —
# в /usr/local/bin (нужен пароль администратора) или в ~/.docker/bin. Во
# втором случае путь дописывается в файл настроек оболочки, и до перезапуска
# терминала оболочка о нём не знает.
#
# Вторая: запуск двойным щелчком из Finder получает урезанный PATH и файлы
# настроек оболочки не читает вовсе — какой бы способ установки ни выбрали.
#
# Поэтому места перечислены явно. Дописывается только то, где команда
# действительно лежит и куда PATH ещё не указывает.

DOCKER_LOOKED_IN=""

for _place in /usr/local/bin "$HOME/.docker/bin" /opt/homebrew/bin \
              /Applications/Docker.app/Contents/Resources/bin; do
    DOCKER_LOOKED_IN="$DOCKER_LOOKED_IN
      $_place"
    case ":$PATH:" in
        *":$_place:"*) ;;
        *) [ -x "$_place/docker" ] && PATH="$PATH:$_place" ;;
    esac
done
unset _place
export PATH
