import React from 'react'

const GUIAS = {
  $geoWithin: {
    titulo: 'Inteiramente dentro da área',
    uso: 'Use para exigir que toda a geometria esteja contida na área de atendimento.',
    detalhe: 'Na rota que cruza a área, só um trecho está dentro: ela fica de fora.',
  },
  $geoIntersects: {
    titulo: 'Interseção com a área',
    uso: 'Use para encontrar geometrias que tenham interseção com a área de atendimento.',
    detalhe: 'Inclui a rota inteiramente dentro e a que passa pela área.',
  },
  $near: {
    titulo: 'Buscar os mais próximos',
    uso: 'Use no find() quando precisa receber documentos ordenados por proximidade.',
    detalhe: 'Ordena do mais perto ao mais longe; não acrescenta a distância ao documento.',
  },
  $nearSphere: {
    titulo: 'Explicitar a consulta esférica',
    uso: 'Use no find() para explicitar que a proximidade considera a geometria esférica.',
    detalhe: 'Com GeoJSON + 2dsphere, equivale ao $near. Não é uma opção mais precisa nesta demo.',
  },
  $geoNear: {
    titulo: 'Usar a distância no pipeline',
    uso: 'Use no aggregate() para devolver a distância e continuar com filtros ou agrupamentos.',
    detalhe: 'Deve abrir o pipeline. Aqui, distanceField devolve a distância em metros.',
  },
}

export default function ComparacaoOperadores({ area, selecionado, onSelecionar, resultados, colecao }) {
  const nomes = area ? ['$geoWithin', '$geoIntersects'] : ['$near', '$nearSphere', '$geoNear']
  return <>
    <div className={`geo-operadores-comparacao ${area ? 'area' : 'proximidade'}`}>
      {nomes.map(nome => {
        const guia = GUIAS[nome]
        const resultado = resultados?.find(r => r.operador === nome)
        return <div key={nome} className="geo-operador-coluna">
          <button className="geo-operador-escolha" aria-pressed={selecionado === nome}
            onClick={() => onSelecionar(nome)}>
            <code>{nome}</code>
            <strong>{guia.titulo}</strong>
            <span>{guia.uso}</span>
            <small>{guia.detalhe}</small>
          </button>
          {!area && resultado && <div className="geo-operador-amostra">
            <p>{resultado.amostra_por_terminal ? 'Um documento por terminal' : 'Transações por proximidade'}
              <br /><code>{resultado.colecao || colecao}</code></p>
            {resultado.amostra.length ? <ol>
              {resultado.amostra.map(a => <li key={a.endToEndId}>
                <code>{a.endToEndId}</code>
                <span>{a.dispositivo?.id && `${a.dispositivo.id} · `}{a.municipio}/{a.uf}</span>
                {a.distanciaMetros != null && <strong>{a.distanciaMetros.toLocaleString('pt-BR')} m</strong>}
              </li>)}
            </ol> : <p>Nenhum documento neste raio.</p>}
          </div>}
        </div>
      })}
    </div>
    {!area && <p className="query-map-note">
      Nesta demo, o pipeline de $geoNear agrupa por terminal e consulta uma cópia da coleção.
      A diferença nas listas inclui esse agrupamento; não é uma diferença de precisão entre operadores.
    </p>}
  </>
}
