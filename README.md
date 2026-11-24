# Solución de un problema de parqueaderos

Simulación en Python de las filas de pago de una salida del centro comercial
Supercentro. Compara tres cajeros independientes con una alternativa de cuatro,
estima cuántas réplicas se requieren para estabilizar el promedio de espera y
presenta resultados antes y después de retirar el estado transitorio.

## Datos del enunciado

| Tipo de usuario | Probabilidad usada | Media entre llegadas (min) | Media de servicio (min) |
|---|---:|---:|---:|
| Rápido | 25 % | 3 | 1 |
| Normal | 20 % | 3 | 3 |
| Lento | 27,5 % | 5 | 4 |
| Muy lento | 27,5 % | 7 | 6 |

El enunciado asigna el 55 % restante conjuntamente a usuarios lentos y muy
lentos, sin especificar el reparto. Para poder simular, se asumió una división
igual: 27,5 % para cada grupo. Cada réplica genera 3.000 vehículos y asigna
cada uno aleatoriamente a una fila FIFO independiente. No se modelan cambios
de fila, abandono ni varias salidas con demandas diferentes; se analiza una
salida representativa.

## Ejecución

Requiere Python 3.10 o posterior y Matplotlib:

```powershell
python -m pip install -r requirements.txt
python .\app_parqueadero.py
```

La aplicación abre `http://127.0.0.1:8765`. Ingresa un máximo de réplicas
múltiplo de 10 (entre 60 y 500) y una semilla. También se puede ejecutar por
terminal:

```powershell
python .\simulacion_parqueadero.py --max-replicas 200 --semilla 2026
```

## Estabilidad y estado transitorio

El programa comprueba cada 10 réplicas el cambio relativo del promedio
acumulado de espera del sistema actual de tres cajeros. Declara estabilidad
cuando el cambio es como máximo 1 % durante cinco comprobaciones consecutivas.
También se grafica la convergencia de la alternativa de cuatro cajeros para
facilitar su comparación. Si no alcanza el criterio, informa que llegó al
máximo solicitado sin converger.

En cada réplica se excluyen los primeros 30 servicios de cada cajero del
promedio principal para reducir el sesgo de iniciar la cola vacía. La tabla y
la gráfica comparan promedios calculados con todos los vehículos frente a los
calculados después de retirar ese tramo transitorio.

## Decisión y alcance del modelo

Se recomienda instalar un cuarto cajero si la reducción emparejada de la espera
es al menos 10 % y el límite inferior de su intervalo de confianza del 95 % es
mayor que cero. Las mismas llegadas, tipos, tiempos de servicio y sorteos de
asignación se reutilizan para comparar escenarios.

Cada cajero tiene una cola FIFO propia y tiempos exponenciales condicionados al
tipo de usuario. Como las medias cambian entre tipos, la mezcla agregada no es
un M/M/1 homogéneo exacto. Los valores analíticos de estabilidad y espera
M/M/1 se reportan como referencias; la espera medida directamente por la
simulación es el resultado principal. La recomendación no incorpora el costo
de instalar cajeros.

## Verificación, calibración y validación

- **Calibración:** los promedios y probabilidades de la tabla son los del
  enunciado; se comprueba que las probabilidades sumen 100 %.
- **Verificación:** pruebas automatizadas comprueban asignación a una sola
  fila, orden FIFO, ausencia de tiempos negativos y resultados reproducibles
  para una semilla fija.
- **Validación:** se compara la convergencia entre réplicas y se contrasta la
  simulación con las referencias teóricas M/M/1, considerando sus limitaciones
  para usuarios con distintas medias.

## Archivos generados

Al ejecutar una comparación se generan:

- `resultados_parqueadero_resumen.csv`: estadísticas por cajero y tipo.
- `resultados_parqueadero_replicas.csv`: conteos y esperas de cada réplica.
- `resultados_parqueadero_convergencia.png`: promedio acumulado y criterio de
  estabilidad.
- `resultados_parqueadero_antes_despues.png`: espera y servicio antes y después
  de retirar el transitorio.

Las gráficas se crean con Matplotlib y se muestran en la interfaz; los cuatro
archivos también se pueden descargar desde la página.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```
