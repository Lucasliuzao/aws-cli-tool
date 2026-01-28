from InquirerPy import inquirer

print("Teste de Fuzzy Search")
print("Tente digitar 'ba' para filtrar 'banana'...")

try:
    choices = [
        {"name": "Apples", "value": "apple"},
        {"name": "Bananas", "value": "banana"},
        {"name": "Cherries", "value": "cherry"},
    ]
    
    result = inquirer.fuzzy(
        message="Selecione uma fruta:",
        choices=choices,
        multiselect=False,
    ).execute()
    
    print(f"Selecionado: {result}")

except Exception as e:
    print(f"Erro: {e}")
