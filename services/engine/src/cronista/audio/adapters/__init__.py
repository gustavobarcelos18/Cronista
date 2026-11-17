"""Adaptadores reais dos modelos de áudio (Fase 2B). Só `prod`, com o grupo opcional `ml` instalado.

As bibliotecas pesadas (PyTorch, faster-whisper, transformers) são importadas **dentro dos métodos**,
por `importlib`, nunca no topo do módulo: importar este pacote não custa nada e o mypy vê o mesmo código
com ou sem o grupo `ml` instalado. Os modelos só são carregados na primeira chamada.
"""
