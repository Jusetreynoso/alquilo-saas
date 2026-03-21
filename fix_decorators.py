import os

filepath = 'c:/Proyectos/sistema_alquilo/gestion_propiedades/views.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("login_url='/admin/login/'", "login_url='/login/'")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
    
print("Replaced all decorator occurrences")
