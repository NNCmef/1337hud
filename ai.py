from google import genai

# Инициализируем клиент (ключ подтягивается автоматически)
client = genai.Client()

# Отправляем запрос к быстрой и универсальной модели
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Придумай 3 интересные темы для пет-проекта."
)

print(response.text)