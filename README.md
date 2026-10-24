# ChutesAI.RevitRender

**ChutesAI.RevitRender** — приложение для AI-визуализации видов Autodesk Revit с использованием генеративных open-source моделей, доступных на платформе [Chutes.ai](https://chutes.ai/).

**ChutesAI.RevitRender** is an application for AI-powered visualization of Autodesk Revit views using generative open-source models available on the [Chutes.ai](https://chutes.ai/) platform.

**Author:** [Alexander Iskra](https://github.com/alxiskra)

---

## RU

[Код приложения](https://github.com/alxiskra/ChutesAI.RevitRender/blob/main/alxiskra.ChutesAI.RevitRender.py) запускается через среду исполнения Dynamo путем его помещения в стандартный узел `PythonScript`

### Возможности

- **Совместимость с Autodesk Revit 2020–2025:**
  - **Revit 2020 / 2021:** Dynamo 2.x, IronPython 2.7, .NET Framework 4.7.2 / 4.8.
  - **Revit 2022 / 2023 / 2024 / 2025:** Dynamo 2.10+, IronPython 2.7 и CPython 3 / PythonNet.

- **Мульти-референсное редактирование изображений:** поддержка модели **Qwen-Image-Edit-2511** с использованием нескольких референсов:
  - Scene #1 — исходный вид из Revit, определяющий геометрию сцены.
  - Scene #2 / Scene #3 — референсы материалов, мебели, картин или других элементов для интеграции в сцену.

- **Поддержка моделей Chutes.ai:** подключение к провайдеру и онлайн-обновление списка доступных моделей через `Connect / Refresh Provider Models`.

- **Управление промптами:** основной промпт (`Main Prompt`), негативный промпт (`Negative Prompt`) и настраиваемый системный промпт (`System Prompt`).

- **Библиотека шаблонов промптов:** возможность создавать, добавлять, обновлять и комбинировать собственные пресеты.

- **Сравнение Before / After:** интерактивное сравнение исходного вида Revit с результатом AI-генерации.

### Настройка и подключение

Для работы с генеративными моделями необходимо:

1. Получить API-ключ формата `cpk_...` на платформе [Chutes.ai](https://chutes.ai/).
2. Вставить API-ключ в соответствующее поле приложения.
3. Выбрать модель и настроить параметры генерации.
4. Нажать `Save`, чтобы сохранить API-ключ и настройки профиля.

Конфигурация сохраняется в файл `profiles.json`, расположенный в директории:

`%AppData%\DynamoChutesAI`

---

## EN

[The application](https://github.com/alxiskra/ChutesAI.RevitRender/blob/main/alxiskra.ChutesAI.RevitRender.py) runs within the Dynamo environment by executing the code in a standard `Python Script` node.

### Features

- **Autodesk Revit 2020–2025 compatibility:**
  - **Revit 2020 / 2021:** Dynamo 2.x, IronPython 2.7, .NET Framework 4.7.2 / 4.8.
  - **Revit 2022 / 2023 / 2024 / 2025:** Dynamo 2.10+, IronPython 2.7, and CPython 3 / PythonNet.

- **Multi-reference image editing:** supports **Qwen-Image-Edit-2511** with multiple reference images:
  - Scene #1 — the original Revit view defining the scene geometry.
  - Scene #2 / Scene #3 — reference images for materials, furniture, artwork, or other elements to incorporate into the scene.

- **Chutes.ai model support:** connect to the provider and refresh the list of available models online using `Connect / Refresh Provider Models`.

- **Prompt management:** includes a `Main Prompt`, `Negative Prompt`, and customizable `System Prompt`.

- **Prompt preset library:** create, add, update, and combine custom prompt presets.

- **Before / After comparison:** interactively compare the original Revit view with the AI-generated result.

### Setup and Configuration

To connect to a generative model:

1. Obtain an API key in the `cpk_...` format from the [Chutes.ai](https://chutes.ai/) platform.
2. Enter the API key in the corresponding field in the application.
3. Select a model and configure the generation settings.
4. Click `Save` to store the API key and profile settings.

Configuration profiles are saved in `profiles.json` in the following directory:

`%AppData%\DynamoChutesAI`

---


## Demo / Демонстрация

[▶ Watch the ChutesAI.RevitRender demo / Смотреть демонстрацию](https://github.com/user-attachments/assets/99215513-72f9-4773-a748-1fc6b66642f8)
