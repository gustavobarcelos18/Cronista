# Estilo do canal: perfil extraído de 5 vídeos de referência

Criado em 2026-11-19. Fonte: 5 vídeos de "100 dias" do próprio criador, em 360p/30 fps, 32 a 52 min (Fallout 4 ×2,
Stranded Deep, Red Dead Redemption 2, GTA). Os arquivos ficam numa pasta local **fora do git**; este documento guarda só
números e descrições. Análise feita por FFmpeg (cenas, silêncio, loudness), quadros amostrados, Whisper e o classificador
de áudio do projeto (AST). Nada disto foi ouvido nem assistido por inteiro por quem escreveu: **o que vem do som é
inferência do classificador**, e a leitura visual vem de amostras (1 quadro a cada 100 s e, em V2, trechos de 40–60 s a 1 quadro/s).

> Cobertura: transcrição completa dos 5 vídeos (atualização de 2026-11-19). Efeitos visuais e som vêm sobretudo de
> V2 (quadros densos e classificador de áudio) e de amostras dos outros; ritmo de corte e volume, dos 5.
> Os números são ponto de partida para calibrar, não metas (histórico §40: qualidade antes de minutagem).
> **Correção:** a primeira versão deste perfil associou as durações aos arquivos na ordem errada, o que errou a duração
> e os cortes por minuto de todos os vídeos (e o silêncio). Os números abaixo estão refeitos com a duração de cada arquivo.

## 1. Números

| Vídeo | Jogo | Duração | Cortes/min (cena > 0,3) | Silêncio | Loudness (LUFS) | Fala (transcrição) |
|---|---|---|---|---|---|---|
| V1 | Fallout 4 (100+ mods) | 33 min | 17 | ~0% | −15,5 | 84% do tempo, 141 palavras/min, 8,9 por frase |
| V2 | Stranded Deep | 32 min | 17 | ~0% | −15,5 | 87%, 159 palavras/min, 8,2 por frase |
| V3 | Red Dead Redemption 2 (justiceiro) | 36 min | 9 | 3% | −20,7 (LRA 15,8) | 84%, 127 palavras/min, 7,9 por frase |
| V4 | GTA V (milionário) | 52 min | 15 | 1% | −12,5 | 77%, 129 palavras/min, 11,7 por frase |
| V5 | Fallout 4 (200+ mods, 1 vida) | 52 min | 14 | ~0% | −17,7 | 83%, 154 palavras/min, 7,3 por frase |

- Cortes/min inclui mudança de cena do próprio jogo (câmera, cinemáticas); é teto, não ritmo de edição. V3 (9/min)
  é o mais lento e o mais cinematográfico, e é o único com variação grande de volume (LRA 15,8) e algum silêncio.
- Intervalo mediano entre cortes: 2,1 a 2,7 s; 90º percentil: 7 a 11 s.
- Narração e fala ao vivo juntas cobrem 77 a 87% do tempo, a 127–159 palavras/min e 7–12 palavras por frase.
  Sempre há fala **ou** música; quase não existe silêncio.
- Faixa de volume −12,5 a −20,7 LUFS; o alvo de −14 do plano fica dentro dela.
- Duração: 32 a 52 min, dentro do alvo de 30–50 min do produto (o V4 passa um pouco).

## 2. Construção do vídeo (5 vídeos transcritos)

**O gancho é um molde fixo (5 de 5), de 40 a 70 s:**
1. **Premissa em uma frase**, quase sempre com "nos próximos 100 dias eu vou…" ("Pelos próximos 100 dias eu vou tentar me
   tornar um serial killer realista", "Nos próximos 100 dias eu vou tentar sobreviver no GTA V, mas tudo é realista",
   "Isso é Fallout 4, mas não como você conhece").
2. **O que torna a série diferente:** mods (V1 mais de 100, V5 mais de 200), realismo (V3, V4) ou desafio (V2).
3. **Regras e objetivos, numerados quando são vários:** V2 tem 3 objetivos ("primeiro… segundo… terceiro, e mais
   importante…"); V3 tem 2 regras ("a primeira regra… a segunda regra…"); V4 tem 1 objetivo ("terminar milionário") mais
   valores pessoais; V5 tem 1 vida ("se eu morrer, já era") e 1 objetivo principal (eliminar a criatura).
4. **Pedido de like encaixado na fala** em V1, V2, V3 e V5 ("já clica no gostei, porque a minha jornada começa agora").
   Em V3 ele é maior (inscrever, curtir, comentar, "isso me ajuda demais"). V4 não tem na abertura.
5. **Virada para o relato:** "e dessa vez a nossa história se inicia aqui em Valentine", "e no primeiro dia aqui estava eu".

**Relato (todos):** primeira pessoa, no passado, em blocos curtos ("Depois disso, dei uma explorada na minha casa",
"Ao sair daquele túnel me deparei com o meu primeiro desafio"). Explica o que fez e por quê, e conta o jogo em ordem.

**Reação ao vivo no meio do relato** ("rema, rema, rema", "olha esse monstro, como tá ficando gigantesco"). A fala ao
vivo não é cortada: ela se alterna com a narração, e a narração volta em seguida.

**Fecho: não é um molde único.** Aparecem três formas:
- **Balanço com números e despedida** (V2, V4): V2 "praticamente 100%, duas ficaram de fora" e Discord na descrição; V4
  "2 milhões e 400 mil dólares, Ferrari, apartamento de 1 milhão" e "finalizo por aqui". Em V4 o fecho diz o número do
  dia final ("17 dias depois do assalto ao banco já era o dia final").
- **Termina na cena final do jogo** (V1, V5): a fala do próprio jogo ("a guerra nunca muda") fecha, e em V1 vem logo
  depois o agradecimento, a lista de mods na descrição e "fui".
- **Gancho para a próxima parte** (V3): termina no meio da história com a fala de um personagem do jogo, sem despedida.

**Marcação de dias** só na tela (contador), não em cartela de tela cheia. A narração conta a história em ordem e só
aponta o dia quando importa ("pelo primeiro dia eu decidi…", "17 dias depois…"), não a cada trecho.

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
7. ~~Terminar a análise dos outros 3 vídeos~~ **Feito para a transcrição** (2026-11-19). Segue pendente medir música×voz
   (ducking) e separar zoom de edição de movimento do jogo por fluxo óptico.
8. **Palavra "jornada" no lint.** O `roteiro-lint` marca "jornada" como `vocabulario_inflado`, mas o criador usa a
   palavra nas próprias aberturas e fechos (V1 "essa jornada", V2 "minha jornada começa agora", V4 "começar a minha
   jornada" e "finalizo a minha jornada"). **Decidido (2026-11-19):** "jornada" saiu da lista do lint, do `/humanizar` e do plano.
9. **Fecho em três formas** (balanço, cena final do jogo, gancho para a próxima parte): a skill hoje só descreve o balanço.

Fora do alcance do app: o humor e a escolha de onde pôr o ícone continuam decisão do criador (o app só sugere).
