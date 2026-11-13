import React from 'react'

// Qual problema de negócio cada painel resolve. São perguntas típicas de cada
// setor, não casos de cliente: o dado da PoV é sintético.
export default function CasoNegocio({ casos }) {
  return (
    <div className="geo-caso" role="note" aria-label="Caso de negócio deste painel">
      <small>caso de negócio</small>
      <ul>
        {casos.map(({ setor, pergunta }) => (
          <li key={setor}><strong>{setor}</strong> · {pergunta}</li>
        ))}
      </ul>
    </div>
  )
}
