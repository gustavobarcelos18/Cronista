# Estilo do canal: perfil extraído de 5 vídeos de referência

Criado em 2026-11-19. Fonte: 5 vídeos de "100 dias" do próprio criador, em 360p/30 fps, 32 a 52 min (Fallout 4 ×2,
Stranded Deep, Red Dead Redemption 2, GTA). Os arquivos ficam numa pasta local **fora do git**; este documento guarda só
números e descrições. Análise feita por FFmpeg (cenas, silêncio, loudness), quadros amostrados, Whisper e o classificador
de áudio do projeto (AST). Nada disto foi ouvido nem assistido por inteiro por quem escreveu: **o que vem do som é
inferência do classificador**, e a leitura visual vem de amostras (1 quadro a cada 100 s e, em V2, trechos de 40–60 s a 1 quadro/s).

> Cobertura: transcrição completa só de V1 e V2; V3, V4 e V5 só têm cenas, volume e quadros amostrados.
> Os números são ponto de partida para calibrar, não metas (histórico §40: qualidade antes de minutagem).

## 1. Números

| Vídeo | Duração | Cortes/min (cena > 0,3) | Silêncio | Loudness (LUFS) | Fala |
|---|---|---|---|---|---|
| V1 Fallout 4 | 32 min | 17 | ~0% | −15,5 | 84% do tempo, 141 palavras/min |
| V2 Stranded Deep | 36 min | 15 | ~0% | −15,5 | 87%, 159 palavras/min |
| V3 Red Dead 2 | 51 min | 6 | 2% | −20,7 (LRA 15,8) | não transcrito |
| V4 GTA | 52 min | 14 | 1% | −12,5 | não transcrito |
| V5 Fallout 4 | 33 min | 21 | ~0% | −17,7 | não transcrito |

- Cortes/min inclui mudança de cena do próprio jogo (câmera, cinemáticas); é teto, não ritmo de edição.
- Intervalo mediano entre cortes: 2,1 a 2,7 s; 90º percentil: 7 a 11 s.
- Frase de narração: 8 a 9 palavras em média. Sempre há fala **ou** música; quase não existe silêncio.
- Faixa de volume −12,5 a −20,7 LUFS; o alvo de −14 do plano fica dentro dela.

## 2. Construção do vídeo (V1 e V2, os dois transcritos)

1. **Gancho de ~40 s.** Premissa em uma frase ("é X, mas não é qualquer X" ou "um oceano imenso, repleto de perigos"),
   a promessa de 100 dias, **os objetivos numerados** (V2 tem 3) e o pedido de like encaixado na fala. A jornada
   "começa agora" no fim do gancho. Já tem música, legenda e título na tela.
2. **Relato em primeira pessoa, no passado**, em blocos curtos: "Depois disso, dei uma explorada na minha casa",
   "Pra não arriscar o bote ser levado pela maré, arrastei ele até a praia". Explica o que fez e por quê.
3. **Reação ao vivo no meio do relato** ("rema, rema, rema", "olha esse monstro, como tá ficando gigantesco"). A fala
   ao vivo não é cortada: ela se alterna com a narração, e a narração volta em seguida.
4. **Fecho.** Interpretação do final do jogo, balanço dos objetivos (V2: "praticamente 100%, duas ficaram de fora" e
   por quê), convite à comunidade (Discord/lista de mods na descrição) e despedida curta ("Fui!").
5. **Marcação de dias** só na tela (contador), não em cartela de tela cheia. A narração não diz "dia N" a todo momento.

## 3. Efeitos visuais (leitura de V2, conferida nas outras amostras)

| Elemento | Como aparece |
|---|---|
| Título do jogo | Logo em tela cheia no 1º segundo |
| Legenda grande | Frases curtas, letras brancas com contorno, **palavra-chave em vermelho**, só em pontos importantes |
| Objetivos | Lista numerada ("1. …", "2. …") que depois fica como **cabeçalho no topo** durante o trecho do objetivo |
| Contador de dias | Fixo no canto superior esquerdo ("DIA 13 - 15", "DIA 16"), numeral em vermelho; agrupa dias e muda a cada trecho |
| Ícone do criador | Rosto em círculo com seta apontando o personagem, em momentos de humor |
| Ícones/selos | "100%" em destaque, ícone de alto-falante, selos pontuais sobre o quadro |
| Tela dividida | Dois lados com legenda em cada um ("COZINHA" / "SALA") e faixas pretas (visto em V4) |
| Zoom e câmera | **Não confirmado**: as amostras não permitem separar zoom de edição de movimento do jogo; medir por fluxo óptico antes de calibrar o zoom |
| Meio dos trechos | Gameplay **quase sem efeito**: os efeitos se concentram em abertura e momentos importantes |

## 4. Som (inferido pelo classificador de áudio)

- **Música o tempo todo** por baixo da voz, trocando de clima (coral épico na abertura, tensa em cenas de risco).
- **Efeitos de edição** nos momentos da imagem: explosão, porta batendo, "tilin", obturador de câmera, zíper (som de
  transição/whoosh), chuva. Aparecem em intervalos de poucos segundos na abertura e menos no meio.
- Ainda não medido: nível relativo música×voz (ducking), e quais efeitos vêm de arquivo e quais são do jogo.

## 5. O que o app já cobre e o que falta

| Elemento do canal | Status no app |
|---|---|
| Zoom e shake em picos | Pronto (Fase 8, render FFmpeg) |
| Cartela de dia | Pronto como título editável na V5; **o canal usa contador fixo no canto** (trilha V4, ver §6) |
| Contador de mortes | Pronto (overlay MOV por `drawtext`) |
| Música com ducking e SFX da biblioteca | Pronto; falta biblioteca preenchida e música por clima (hoje "nenhuma trilha para o clima 'tenso'") |
| LUT por série | Pronto (editável; sem conferência no Resolve) |
| **Legenda grande com palavra em destaque** | Fora da Fase 8 (histórico §57); precisa das palavras do Whisper |
| **Objetivos numerados + cabeçalho persistente** | Não existe |
| **Contador de dias fixo no canto** | Não existe (hoje só cartela de abertura de capítulo) |
| **Ícone/seta do criador, selos** | Não existe (exige biblioteca de assets) |
| **Tela dividida** | Não existe |
| **Gancho de ~40 s com objetivos e título** | Não existe; o roteiro (skill `/roteirizar`) não conhece esse molde |
| **Fecho (balanço, Discord, "Fui!")** | Não existe como molde |
| Densidade de música e SFX da abertura | O orçamento por minuto é por efeito, sem noção de "abertura mais densa que o meio" |

## 6. Propostas (para decidir, nada implementado)

1. **Molde de roteiro do canal** na skill `/roteirizar`: gancho (premissa, objetivos, pedido de like), relato em
   primeira pessoa no passado, fecho (balanço, comunidade, despedida). **Feito na skill e no pacote (2026-11-19, histórico §67).** O teste na sessão 1 mostrou que gancho e fecho não cabem nas lacunas; por isso o pacote reserva as janelas `@gancho` (45 s) e `@fecho` (35 s), fora das lacunas (histórico §67).
2. **Contador de dias fixo** (V4) a partir dos dias do Studio, em MOV com alfa por `drawtext`, no mesmo caminho do
   contador de mortes. Substitui a cartela de capítulo ou convive com ela.
3. **Legenda destacada** (adiada na Fase 8): palavras do Whisper + lista de palavras-chave marcada pelo criador, texto
   branco com a palavra-chave na cor de destaque do brand kit. Só em pontos importantes.
4. **Objetivos como cabeçalho:** entrada declarativa no estilo da série (lista numerada) que vira abertura + cabeçalho.
5. **Densidade por posição:** orçamento de efeitos maior nos primeiros 60 s do vídeo e perto dos picos.
6. **Biblioteca de assets do criador** (ícone com seta, selos, "100%") entra pela biblioteca pessoal já existente
   (licença e origem por item), sem Remotion.
7. Terminar a análise dos outros 3 vídeos (transcrição, e medir música×voz) antes de fixar números.

Fora do alcance do app: o humor e a escolha de onde pôr o ícone continuam decisão do criador (o app só sugere).
