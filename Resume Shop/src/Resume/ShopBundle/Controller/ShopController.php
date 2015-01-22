<?php
/**
 * Created by JetBrains PhpStorm.
 * Author: Ilya_TT (ilya.tt07@gmail.com)
 * Date: 21.01.15
 * Time: 14:14
 */

namespace Resume\ShopBundle\Controller;

use Symfony\Bundle\FrameworkBundle\Controller\Controller;
use Sensio\Bundle\FrameworkExtraBundle\Configuration\Route;
use Sensio\Bundle\FrameworkExtraBundle\Configuration\Template;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;

class ShopController extends Controller
{
	/**
	 * @Route("/", name="shop_home")
	 */
	public function indexAction(Request $request)
	{
		return $this->forward('ResumeShopBundle:Shop:products', [], [
			'page' => $request->query->get('page', 1),
			'search' => $request->query->get('search', ''),
			'title' => 'Все товары'
		]);
	}

	/**
	 * @Route("/{filter}/{id}/", name="shop_filter", requirements={"filter" = "(category|provider)", "id" = "\d+"})
	 */
	public function filterAction(Request $request, $filter, $id)
	{
		// получим текущий объект фильтра
		$object = $this->getDoctrine()
			->getRepository('ResumeShopBundle:'.ucfirst($filter))
			->find($id);

		return $this->forward('ResumeShopBundle:Shop:products', [
			$filter => $id
		], [
			'page' => $request->query->get('page', 1),
			'search' => $request->query->get('search', ''),
			'title' => ($filter == 'category' ? 'Категория' : 'Производитель'). ': '. ($object ? $object->getName() : 'Отсутствует')
		]);
	}

	public function productsAction(Request $request, $category = 0, $provider = 0)
	{
		// словарь активных id
		$actives_id = [
			'category' => $category,
			'provider' => $provider,
		];

		// готовим запрос
		$query = $this->getDoctrine()->getManager()
			->createQueryBuilder()
			->select('p')
			->from('ResumeShopBundle:Product', 'p')
			->innerJoin('p.caterodies','c')
			->innerJoin('p.provider','pr');

		/* в зависимости от наличия фильтров - редактируем начальный запрос */

		if($category){
			$query = $query->andWhere('c.id = :category')->setParameter('category', $category);
		}

		if($provider){
			$query = $query->andWhere('pr.id = :provider')->setParameter('provider', $provider);
		}

		if($search = $request->query->get('search', '')){
			$query = $query->andWhere( $query->expr()->like('p.name', ':search') )->setParameter('search', '%'.$search.'%');
		}

		// имя текущего блока
		$title = $request->query->get('title');

		// параметры отрисовки страницы
		$params = [
			'content' => $this->renderView('ResumeShopBundle:Shop:products.html.twig', [
				'pagination' => $this->get('knp_paginator')->paginate(
					$query,
					$request->query->get('page', 1),
					$this->container->getParameter('limit_products')
				),
				'title' => $title,
				'search' => $search,
			]),
			'title' => $title,
			'actives_id' => $actives_id,
			'search' => $search,
		];

		// в зависимости от типа запроса отдаем либо json либо полную страницу
		if($request->isXmlHttpRequest()){
			return new Response(json_encode($params), 200, ['Content-Type'=>'application/json']);
		}
		else{
			return $this->render('ResumeShopBundle:Shop:productsPage.html.twig', $params);
		}
	}


	/**
	 * @Template()
	 */
	public function allForFilterAction($filter, $id_active)
	{
		return [
			'filter' 	=> $filter,
			'items' 	=> $this->getDoctrine()->getRepository('ResumeShopBundle:'.ucfirst($filter))->findAll(),
			'id_active' => $id_active
		];
	}


}